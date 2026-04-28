"""Upload OpenAI Batch request files from a named queue to the Batch API.

Create a subdirectory under the queue base and place batch__*.jsonl files there:
  data/llm-eval/requests/input-queues/openai-batch/<queue-name>/

Then run:
  python openai_batch_upload.py --queue <queue-name>

The upload result is recorded in:
  data/llm-eval/requests/input-queues/openai-batch/<queue-name>/upload_mapping.json

Files already present in the mapping are skipped (use --overwrite to re-upload).
The queue directory is NOT automatically cleared after upload.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_json, write_json

QUEUE_BASE = PROJECT_ROOT / "data" / "llm-eval" / "requests" / "input-queues" / "openai-batch"


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _list_queues(queue_base: Path) -> list[str]:
    if not queue_base.exists():
        return []
    return sorted(d.name for d in queue_base.iterdir() if d.is_dir())


def _load_mapping(mapping_file: Path) -> dict:
    if mapping_file.exists():
        data = read_json(mapping_file)
        if isinstance(data, dict):
            return data
    return {}


def _save_mapping(mapping_file: Path, mapping: dict) -> None:
    write_json(mapping_file, mapping, indent=2)


def _iter_queue_files(queue_dir: Path) -> list[Path]:
    return sorted(
        p for p in queue_dir.iterdir()
        if p.is_file() and p.suffix == ".jsonl" and p.name.startswith("batch__")
    )


def upload_one(request_file: Path, mapping: dict, dry_run: bool) -> dict:
    from dotenv import load_dotenv
    from openai import OpenAI

    key = request_file.name

    if dry_run:
        return {"status": "dry_run", "key": key, "batch_id": None}

    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI()

    with request_file.open("rb") as fh:
        uploaded = client.files.create(file=fh, purpose="batch")
    file_id = uploaded.id

    batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    batch_id = batch.id

    mapping[key] = {
        "batch_id": batch_id,
        "input_file_id": file_id,
        "source_file": _relpath(request_file),
        "uploaded_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    return {"status": "uploaded", "key": key, "batch_id": batch_id}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload batch__*.jsonl files from a named queue to the OpenAI Batch API."
    )
    parser.add_argument("--queue-base", type=Path, default=QUEUE_BASE,
                        help=f"Base directory for queues (default: {_relpath(QUEUE_BASE)})")
    parser.add_argument("--queue", type=str, default=None,
                        help="Queue subdirectory name (e.g. queue1)")
    parser.add_argument("--overwrite", action="store_true", help="Re-upload files already in mapping")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without calling the API")
    args = parser.parse_args()

    queue_base = args.queue_base.resolve()

    if args.queue is None:
        available = _list_queues(queue_base)
        print(f"--queue is required. Specify a subdirectory under {_relpath(queue_base)}/")
        if available:
            print(f"Available queues: {', '.join(available)}")
        else:
            print(f"No queues found. Create a subdirectory and place batch__*.jsonl files there.")
        return 1

    queue_dir = queue_base / args.queue
    mapping_file = queue_dir / "upload_mapping.json"

    if not queue_dir.exists():
        print(f"Queue directory does not exist: {_relpath(queue_dir)}")
        available = _list_queues(queue_base)
        if available:
            print(f"Available queues: {', '.join(available)}")
        return 1

    queue_files = _iter_queue_files(queue_dir)

    if not queue_files:
        print(f"No batch__*.jsonl files found in queue: {_relpath(queue_dir)}")
        return 1

    mapping = _load_mapping(mapping_file)

    new_files = [f for f in queue_files if f.name not in mapping]
    already_uploaded = [f for f in queue_files if f.name in mapping]

    print(f"Queue: {_relpath(queue_dir)}")
    print(f"  Total files  : {len(queue_files)}")
    print(f"  New          : {len(new_files)}")
    if already_uploaded:
        suffix = "(will re-upload)" if args.overwrite else "(skipped — already in mapping)"
        print(f"  Already sent : {len(already_uploaded)} {suffix}")

    upload_targets = queue_files if args.overwrite else new_files

    if not upload_targets:
        print("\nNothing to upload.")
        return 0

    print()
    print("Files to upload:")
    for f in upload_targets:
        print(f"  {f.name}")
    print()

    if not args.dry_run and not args.yes:
        try:
            answer = input(f"Upload {len(upload_targets)} file(s) to OpenAI Batch API? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer != "y":
            print("Aborted.")
            return 1

    total = len(upload_targets)
    w = len(str(total))
    n_uploaded = 0
    n_dry = 0

    for idx, request_file in enumerate(upload_targets, start=1):
        print(f"[{idx:{w}}/{total}] {request_file.name}")
        try:
            result = upload_one(request_file, mapping, dry_run=args.dry_run)
        except Exception as e:
            print(f"  [ERROR] {e}")
            continue

        if result["status"] == "uploaded":
            print(f"  batch_id: {result['batch_id']}")
            n_uploaded += 1
        elif result["status"] == "dry_run":
            print(f"  (dry-run)")
            n_dry += 1

    if n_uploaded > 0:
        _save_mapping(mapping_file, mapping)
        print(f"\nMapping saved -> {_relpath(mapping_file)}")

    parts = []
    if n_uploaded:
        parts.append(f"{n_uploaded} uploaded")
    if n_dry:
        parts.append(f"{n_dry} dry-run")
    print(f"Total: {total} files ({', '.join(parts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
