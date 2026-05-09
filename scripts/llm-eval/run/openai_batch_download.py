"""Download completed OpenAI Batch jobs and save responses.

Reads mapping from:
  data/llm-eval/requests/input-queues/openai-batch/<queue-name>/upload_mapping.json

Run:
  python openai_batch_download.py --queue <queue-name>

Saves responses to:
  data/llm-eval/responses/openai-batch/{slug}/{prompting_condition}/{dataset_variant}/{n-rule}/
    response__{slug}__{op}__{type}__{rule}__n{N}__...__batch_{batch_id}__{YYYYMMDDHHMMSS}.jsonl

Completed entries are removed from the mapping.
In-progress / pending entries remain in the mapping for the next run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_json, write_json

QUEUE_BASE = PROJECT_ROOT / "data" / "llm-eval" / "requests" / "input-queues" / "openai-batch"
DEFAULT_RESPONSE_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "responses" / "openai-batch"

_PENDING_STATUSES = {"validating", "in_progress", "finalizing"}
_FAILED_STATUSES = {"failed", "expired", "cancelled", "cancelling"}


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
    if not mapping_file.exists():
        print(f"Mapping file not found: {_relpath(mapping_file)}")
        print("Run openai_batch_upload.py --queue <queue-name> first.")
        raise SystemExit(1)
    data = read_json(mapping_file)
    if not isinstance(data, dict):
        print(f"Invalid mapping file format: {_relpath(mapping_file)}")
        raise SystemExit(1)
    return data


def _save_mapping(mapping_file: Path, mapping: dict) -> None:
    write_json(mapping_file, mapping, indent=2)


def _parse_batch_stem(stem: str) -> dict | None:
    if not stem.startswith("batch__"):
        return None
    parts = stem[len("batch__"):].split("__")
    if len(parts) < 4:
        return None
    return {
        "slug": parts[0],
        "prompting_condition": parts[1],
        "dataset_variant": parts[2],
        "pattern_id": parts[3],
    }


def _response_path(entry: dict, response_root: Path, completed_at: int | None = None) -> Path:
    from datetime import datetime, timezone

    source_file = entry.get("source_file", "")
    batch_id: str = entry.get("batch_id", "unknown")

    stem = Path(source_file).stem if source_file else Path(entry.get("key", "unknown.jsonl")).stem
    meta = _parse_batch_stem(stem)
    response_stem = stem.replace("batch__", "response__", 1)

    if completed_at is not None:
        ts = datetime.fromtimestamp(completed_at, tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        new_name = f"{response_stem}__{batch_id}__{ts}.jsonl"
    else:
        new_name = f"{response_stem}__{batch_id}.jsonl"

    if meta:
        rule_dir = f"{meta['pattern_id'].count('_') + 1}-rule"
        return response_root / meta["slug"] / meta["prompting_condition"] / meta["dataset_variant"] / rule_dir / new_name
    else:
        return response_root / new_name


def download_one(
    key: str,
    entry: dict,
    response_root: Path,
    overwrite: bool,
    verbose: bool,
) -> str:
    """Returns one of: completed, pending, failed, error, skipped_exists."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI()
    batch_id: str = entry["batch_id"]

    batch = client.batches.retrieve(batch_id)
    status = batch.status

    if verbose:
        print(f"  batch_id : {batch_id}")
        print(f"  status   : {status}")

    if status in _PENDING_STATUSES:
        if verbose:
            counts = batch.request_counts
            if counts:
                print(f"  progress : {counts.completed}/{counts.total} completed")
        return "pending"

    if status in _FAILED_STATUSES:
        print(f"  [WARN] terminal status={status}")
        return "failed"

    if status != "completed":
        print(f"  [WARN] unexpected status={status}")
        return "error"

    output_file_id = getattr(batch, "output_file_id", None)
    if not output_file_id:
        print(f"  [WARN] no output_file_id for completed batch")
        return "error"

    completed_at: int | None = getattr(batch, "completed_at", None)
    out_path = _response_path(entry, response_root, completed_at)

    if out_path.exists() and not overwrite:
        if verbose:
            print(f"  SKIP (exists): {_relpath(out_path)}")
        return "skipped_exists"

    raw_bytes = client.files.content(output_file_id).read()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw_bytes)

    print(f"  -> {_relpath(out_path)}")
    return "completed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download completed OpenAI Batch jobs and save responses."
    )
    parser.add_argument("--queue-base", type=Path, default=QUEUE_BASE,
                        help=f"Base directory for queues (default: {_relpath(QUEUE_BASE)})")
    parser.add_argument("--queue", type=str, default=None,
                        help="Queue subdirectory name (e.g. queue1)")
    parser.add_argument("--response-root", type=Path, default=DEFAULT_RESPONSE_ROOT)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing response files")
    parser.add_argument("--verbose", action="store_true", help="Print detailed per-batch info")
    args = parser.parse_args()

    queue_base = args.queue_base.resolve()

    if args.queue is None:
        available = _list_queues(queue_base)
        print(f"--queue is required. Specify a subdirectory under {_relpath(queue_base)}/")
        if available:
            print(f"Available queues: {', '.join(available)}")
        else:
            print(f"No queues found.")
        return 1

    queue_dir = queue_base / args.queue
    mapping_file = queue_dir / "upload_mapping.json"

    if not queue_dir.exists():
        print(f"Queue directory does not exist: {_relpath(queue_dir)}")
        available = _list_queues(queue_base)
        if available:
            print(f"Available queues: {', '.join(available)}")
        return 1

    response_root = args.response_root.resolve()

    mapping = _load_mapping(mapping_file)

    if not mapping:
        print("No entries in mapping. Nothing to download.")
        return 0

    total = len(mapping)
    w = len(str(total))

    remaining: dict = {}
    n_completed = 0
    n_pending = 0
    n_failed = 0
    n_skipped = 0
    n_error = 0

    for idx, (key, entry) in enumerate(mapping.items(), start=1):
        print(f"[{idx:{w}}/{total}] {key}")

        try:
            result = download_one(
                key=key,
                entry=entry,
                response_root=response_root,
                overwrite=args.overwrite,
                verbose=args.verbose,
            )
        except Exception as e:
            print(f"  [ERROR] {e}")
            remaining[key] = entry
            n_error += 1
            continue

        if result == "completed":
            n_completed += 1
        elif result == "skipped_exists":
            n_skipped += 1
        elif result == "pending":
            remaining[key] = entry
            n_pending += 1
            print(f"  still in progress")
        elif result == "failed":
            n_failed += 1
        else:
            remaining[key] = entry
            n_error += 1

    _save_mapping(mapping_file, remaining)

    print()
    parts = []
    if n_completed:
        parts.append(f"{n_completed} completed")
    if n_skipped:
        parts.append(f"{n_skipped} already downloaded")
    if n_pending:
        parts.append(f"{n_pending} still in progress")
    if n_failed:
        parts.append(f"{n_failed} failed/expired")
    if n_error:
        parts.append(f"{n_error} errors")
    print(f"Total: {total} batches ({', '.join(parts)})")

    if n_pending:
        print(f"Re-run this script later to download the remaining {n_pending} batch(es).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
