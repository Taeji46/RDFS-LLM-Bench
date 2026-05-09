"""Run sequential inference via Ollama.

Create a subdirectory under the queue base and place seq__*.jsonl files there:
  data/llm-eval/requests/input-queues/ollama/<queue-name>/

Then run:
  python run_sequential_ollama.py --queue <queue-name>

To use a remote Ollama host, set OLLAMA_HOST in .env and pass --use-host:
  OLLAMA_HOST=http://<host>:<port>
  python run_sequential_ollama.py --queue <queue-name> --use-host

Or pass the URL directly as a one-off override:
  python run_sequential_ollama.py --queue <queue-name> --ollama-host http://<host>:<port>

If neither is specified, the local Ollama daemon is used.

Files already having a response are skipped (use --overwrite to re-run).
The queue directory is NOT automatically cleared after processing.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any
from datetime import datetime, timedelta, timezone
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from shared.io import read_json, read_jsonl, write_jsonl

QUEUE_BASE = PROJECT_ROOT / "data" / "llm-eval" / "requests" / "input-queues" / "ollama"
DEFAULT_RESPONSE_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "responses" / "sequential"
MODEL_CONFIG_PATH = LLM_EVAL_DIR / "model-config.json"


def _load_model_config() -> dict[str, dict]:
    config = read_json(MODEL_CONFIG_PATH)
    if not isinstance(config, dict):
        raise SystemExit(f"Invalid model-config.json: {MODEL_CONFIG_PATH}")
    return {slug: v for slug, v in config.items() if v.get("runner") == "sequential-ollama"}


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _list_queues(queue_base: Path) -> list[str]:
    if not queue_base.exists():
        return []
    return sorted(d.name for d in queue_base.iterdir() if d.is_dir())


def _format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m{int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h{int((seconds % 3600) // 60)}m{int(seconds % 60)}s"


def _stem_prefix(req_stem: str) -> str:
    return "response__" + req_stem[len("seq__"):]


def _has_existing_response(response_dir: Path, stem_prefix: str) -> Path | None:
    if not response_dir.exists():
        return None
    matches = list(response_dir.glob(stem_prefix + "__*.jsonl"))
    return matches[0] if matches else None


def _parse_seq_stem(stem: str) -> dict | None:
    if not stem.startswith("seq__"):
        return None
    parts = stem[len("seq__"):].split("__")
    if len(parts) < 4:
        return None
    return {
        "slug": parts[0],
        "prompting_condition": parts[1],
        "dataset_variant": parts[2],
        "pattern_id": parts[3],
    }


def _response_dir(response_root: Path, meta: dict) -> Path:
    rule_dir = f"{meta['pattern_id'].count('_') + 1}-rule"
    return response_root / meta["slug"] / meta["prompting_condition"] / meta["dataset_variant"] / rule_dir


def run_file(
    req_path: Path,
    response_root: Path,
    overwrite: bool,
    verbose: bool,
    file_idx: int,
    total_files: int,
    global_stats: dict,
    ollama_client: Any,
) -> dict:
    stem = req_path.stem
    meta = _parse_seq_stem(stem)
    if meta is None:
        return {"status": "skipped_parse_error", "path": str(req_path)}

    slug = meta["slug"]
    op = meta["prompting_condition"]
    dtype = meta["dataset_variant"]
    pattern_id = meta["pattern_id"]

    response_dir = _response_dir(response_root, meta)
    stem_prefix = _stem_prefix(stem)

    existing = _has_existing_response(response_dir, stem_prefix)
    if existing and not overwrite:
        if verbose:
            print(f"SKIP (exists): {existing}")
        return {"status": "skipped_exists", "slug": slug, "op": op, "dtype": dtype, "pattern_id": pattern_id}

    rows = read_jsonl(req_path)
    if not rows:
        return {"status": "skipped_empty", "slug": slug, "op": op, "dtype": dtype, "pattern_id": pattern_id}

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    out_path = response_dir / f"{stem_prefix}__{ts}.jsonl"

    file_start = time.time()
    file_times: list[float] = []
    results: list[dict] = []

    print(f"[file {file_idx}/{total_files}] {op}/{dtype}/{pattern_id}  ({len(rows)} requests)")

    for req_idx, row in enumerate(rows, 1):
        req_id = str(row.get("id", f"request-{req_idx}"))
        model = str(row.get("model", ""))
        user_input = str(row.get("input", ""))
        system_prompt: str | None = row.get("system")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        t0 = time.time()
        content = ""
        for attempt in range(1, 6):
            try:
                resp: Any = ollama_client.chat(model=model, messages=messages)
                content = resp.message.content or ""
                if content:
                    break
                if attempt < 5:
                    wait = 2 ** attempt
                    print(f"  [WARN] {req_id} attempt {attempt} empty response  retrying in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  [ERROR] {req_id} all 5 attempts returned empty response")
            except Exception as exc:
                if attempt < 5:
                    wait = 2 ** attempt
                    print(f"  [WARN] {req_id} attempt {attempt} failed: {exc}  retrying in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  [ERROR] {req_id} all 5 attempts failed: {exc}")

        elapsed = time.time() - t0
        file_times.append(elapsed)
        global_stats["processed"] += 1
        results.append({"id": req_id, "response": content})

        global_elapsed = time.time() - global_stats["start"]
        avg_global = global_elapsed / global_stats["processed"]
        remaining_global = (global_stats["total"] - global_stats["processed"]) * avg_global
        eta_abs = datetime.now() + timedelta(seconds=remaining_global)
        avg_file = sum(file_times) / len(file_times)
        remaining_file = (len(rows) - req_idx) * avg_file

        print(
            f"  [{req_idx}/{len(rows)}] id={req_id}  {elapsed:.1f}s  "
            f"file-ETA:{_format_eta(remaining_file)}  "
            f"global-ETA:{_format_eta(remaining_global)} "
            f"({eta_abs.strftime('%H:%M:%S')})"
        )

    write_jsonl(out_path, results)
    file_elapsed = time.time() - file_start
    avg = file_elapsed / len(rows) if rows else 0
    print(f"  -> saved {len(results)} responses  avg {avg:.1f}s/req  total {_format_eta(file_elapsed)}")
    print(f"  -> {out_path}")

    return {"status": "written", "slug": slug, "op": op, "dtype": dtype, "pattern_id": pattern_id, "count": len(results)}


def main() -> int:
    import ollama as ollama_lib

    model_config = _load_model_config()

    parser = argparse.ArgumentParser(description="Run sequential inference via Ollama.")
    parser.add_argument("--queue-base", type=Path, default=QUEUE_BASE,
                        help=f"Base directory for queues (default: {_relpath(QUEUE_BASE)})")
    parser.add_argument("--queue", type=str, default=None,
                        help="Queue subdirectory name (e.g. queue1)")
    parser.add_argument("--response-root", type=Path, default=DEFAULT_RESPONSE_ROOT)
    parser.add_argument("--use-host", action="store_true",
                        help="Use remote Ollama host defined by $OLLAMA_HOST in .env")
    parser.add_argument("--ollama-host", type=str, default=None,
                        help="Ollama host URL (one-off override, ignores $OLLAMA_HOST)")
    parser.add_argument("--overwrite", action="store_true", help="Re-run files that already have a response")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without calling Ollama")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.ollama_host:
        ollama_host = args.ollama_host
    elif args.use_host:
        ollama_host = os.environ.get("OLLAMA_HOST")
        if not ollama_host:
            raise SystemExit("--use-host specified but OLLAMA_HOST is not set in .env")
    else:
        ollama_host = None
    ollama_client = ollama_lib.Client(host=ollama_host, timeout=300) if ollama_host else ollama_lib.Client(timeout=300)
    print(f"Ollama host: {ollama_host or 'local'}")

    queue_base = args.queue_base.resolve()
    response_root = args.response_root.resolve()

    if args.queue is None:
        available = _list_queues(queue_base)
        print(f"--queue is required. Specify a subdirectory under {_relpath(queue_base)}/")
        if available:
            print(f"Available queues: {', '.join(available)}")
        else:
            print(f"No queues found. Create a subdirectory and place seq__*.jsonl files there.")
        return 1

    queue_dir = queue_base / args.queue

    if not queue_dir.exists():
        print(f"Queue directory does not exist: {_relpath(queue_dir)}")
        available = _list_queues(queue_base)
        if available:
            print(f"Available queues: {', '.join(available)}")
        return 1

    queue_files = sorted(
        p for p in queue_dir.iterdir()
        if p.is_file() and p.suffix == ".jsonl" and p.name.startswith("seq__")
    )

    if not queue_files:
        print(f"No seq__*.jsonl files found in queue: {_relpath(queue_dir)}")
        return 1

    # filter to models handled by this runner
    filtered: list[Path] = []
    skipped_runner: list[Path] = []
    for p in queue_files:
        meta = _parse_seq_stem(p.stem)
        if meta is None:
            continue
        if meta["slug"] not in model_config:
            skipped_runner.append(p)
            continue
        filtered.append(p)

    print(f"Queue: {_relpath(queue_dir)}")
    print(f"  Total files       : {len(queue_files)}")
    print(f"  This runner       : {len(filtered)}")
    if skipped_runner:
        print(f"  Other runner      : {len(skipped_runner)} (skipped)")

    if not filtered:
        print("\nNothing to run.")
        return 0

    already_done = [
        p for p in filtered
        if _has_existing_response(_response_dir(response_root, _parse_seq_stem(p.stem)), _stem_prefix(p.stem))  # type: ignore[arg-type]
    ]
    new_files = [p for p in filtered if p not in already_done]

    if already_done:
        suffix = "(will re-run)" if args.overwrite else "(skipped — response exists)"
        print(f"  Already done      : {len(already_done)} {suffix}")

    run_targets = filtered if args.overwrite else new_files

    if not run_targets:
        print("\nNothing to run.")
        return 0

    total_requests = sum(len(read_jsonl(p)) for p in run_targets)

    print()
    print("Files to run:")
    for p in run_targets:
        print(f"  {p.name}")
    print(f"\nTotal requests: {total_requests}")
    print()

    if not args.dry_run and not args.yes:
        try:
            answer = input(f"Run {len(run_targets)} file(s) via Ollama? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer != "y":
            print("Aborted.")
            return 1

    if args.dry_run:
        print("(dry-run — no Ollama calls made)")
        return 0

    print("=" * 70)
    global_stats = {"start": time.time(), "processed": 0, "total": total_requests}
    records: list[dict] = []

    for file_idx, req_path in enumerate(run_targets, 1):
        record = run_file(
            req_path=req_path,
            response_root=response_root,
            overwrite=args.overwrite,
            verbose=args.verbose,
            file_idx=file_idx,
            total_files=len(run_targets),
            global_stats=global_stats,
            ollama_client=ollama_client,
        )
        records.append(record)

    n_written = sum(1 for r in records if r["status"] == "written")
    n_skipped = sum(1 for r in records if r["status"] == "skipped_exists")
    parts = [f"{n_written} written"]
    if n_skipped:
        parts.append(f"{n_skipped} skipped")
    print(f"\nTotal: {len(records)} files ({', '.join(parts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
