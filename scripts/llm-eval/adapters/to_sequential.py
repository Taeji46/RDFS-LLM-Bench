"""Convert zero-shot tasks to sequential-request JSONL files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_json, write_jsonl
from shared.prompt_builder import normalize_prompting_condition
from shared.rule_defs import DEFAULT_SYSTEM_PROMPT, PROMPTING_CONDITIONS

DEFAULT_ZEROSHOT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "tasks" / "zeroshot"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "requests" / "sequential"
MODEL_CONFIG_PATH = LLM_EVAL_DIR / "model-config.json"


def _load_model_config(runner_prefix: str) -> dict[str, dict]:
    """Return {slug: {runner, api_model}} for models matching the given runner prefix."""
    config = read_json(MODEL_CONFIG_PATH)
    if not isinstance(config, dict):
        print(f"Invalid model-config.json: {MODEL_CONFIG_PATH}")
        raise SystemExit(1)
    return {slug: v for slug, v in config.items() if v.get("runner", "").startswith(runner_prefix)}


def _csv_items(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _resolve_prompting_conditions(raw: str) -> list[str]:
    if not raw.strip():
        return list(PROMPTING_CONDITIONS)

    prompting_conditions: list[str] = []
    for item in _csv_items(raw):
        prompting_condition = normalize_prompting_condition(item)
        if prompting_condition not in prompting_conditions:
            prompting_conditions.append(prompting_condition)
    return prompting_conditions


def _iter_task_files(zeroshot_root: Path, prompting_conditions: list[str]) -> list[Path]:
    files: list[Path] = []
    for prompting_condition in prompting_conditions:
        base = zeroshot_root / prompting_condition
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("task__*.json")))
    return files


def _rule_dir_from_rule(pattern_id: str) -> str:
    return f"{pattern_id.count('_') + 1}-rule"


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _required_str(metadata: dict, key: str, task_path: Path) -> str:
    value = str(metadata.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing metadata.{key}: {task_path}")
    return value


def convert_one(
    task_path: Path,
    payload: dict,
    output_root: Path,
    slug: str,
    api_model: str,
    include_system: bool,
    overwrite: bool,
    verbose: bool = False,
) -> dict:
    metadata = payload.get("metadata", {})
    tasks = payload.get("tasks", [])
    if not isinstance(metadata, dict) or not isinstance(tasks, list):
        raise ValueError(f"invalid zero-shot task structure: {task_path}")

    prompting_condition = _required_str(metadata, "prompting_condition", task_path)
    dataset_variant = _required_str(metadata, "dataset_variant", task_path)
    pattern_id = _required_str(metadata, "pattern_id", task_path)
    source_uid: str | None = metadata.get("source_uid") or None
    build_uid = _required_str(metadata, "build_uid", task_path)
    template_uid = _required_str(metadata, "template_uid", task_path)
    rule_dir = str(metadata.get("rule_dir") or _rule_dir_from_rule(pattern_id))

    rows: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        row = {
            "id": str(task.get("task_id", "")),
            "model": api_model,
            "input": str(task.get("user_prompt", "")),
        }
        if include_system:
            row["system"] = str(task.get("system_prompt", DEFAULT_SYSTEM_PROMPT))
        rows.append(row)

    out_dir = output_root / slug / prompting_condition / dataset_variant / rule_dir
    if source_uid is not None:
        out_name = (
            f"seq__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__"
            f"n{len(rows)}__{source_uid}__{build_uid}__{template_uid}.jsonl"
        )
    else:
        out_name = (
            f"seq__{slug}__{prompting_condition}__{dataset_variant}__{pattern_id}__"
            f"n{len(rows)}__{build_uid}__{template_uid}.jsonl"
        )
    out_path = out_dir / out_name

    if out_path.exists() and not overwrite:
        if verbose:
            print(f"SKIP (exists): {out_path}")
        return {
            "status": "skipped_exists",
            "prompting_condition": prompting_condition,
            "dataset_variant": dataset_variant,
            "pattern_id": pattern_id,
            "model": slug,
            "count": len(rows),
            "source_task_file": _relpath(task_path),
            "request_file": _relpath(out_path),
        }

    write_jsonl(out_path, rows)
    if verbose:
        print(f"Saved {len(rows)} requests -> {out_path}")

    return {
        "status": "written",
        "prompting_condition": prompting_condition,
        "dataset_variant": dataset_variant,
        "pattern_id": pattern_id,
        "model": slug,
        "count": len(rows),
        "source_task_file": _relpath(task_path),
        "request_file": _relpath(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert zero-shot tasks to sequential request JSONL.")
    parser.add_argument("--zeroshot-root", type=Path, default=DEFAULT_ZEROSHOT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    model_config = _load_model_config("sequential")
    parser.add_argument("--model", type=str, required=True,
                        help=f"Model slug. Available: {', '.join(model_config) or '(none defined)'}")
    parser.add_argument("--prompting-conditions", type=str, default=",".join(PROMPTING_CONDITIONS), help="Comma-separated prompting conditions (e.g. NRP-full,NRP-name)")
    parser.add_argument("--dataset-variants", type=str, default="", help="Comma-separated dataset variants")
    parser.add_argument("--patterns", type=str, default="", help="Comma-separated pattern ids")
    parser.add_argument("--max-files", type=int, default=0, help="Debug option: process first N files")
    parser.add_argument("--include-system", action="store_true", help="Include system field in each request row")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing request files")
    parser.add_argument("--verbose", action="store_true", help="Print each saved file path")
    args = parser.parse_args()

    if args.model not in model_config:
        print(f"Unknown model: {args.model}")
        if model_config:
            print(f"Available (sequential): {', '.join(model_config)}")
        else:
            print("No sequential models defined yet.")
        print(f"Add it to {MODEL_CONFIG_PATH} to use it.")
        return 1

    slug      = args.model
    api_model = model_config[slug]["api_model"]

    zeroshot_root = args.zeroshot_root.resolve()
    output_root = args.output_root.resolve()

    prompting_conditions = _resolve_prompting_conditions(args.prompting_conditions)
    dataset_filter = set(_csv_items(args.dataset_variants))
    rule_filter = set(_csv_items(args.patterns))

    task_files = _iter_task_files(zeroshot_root, prompting_conditions)
    if args.max_files > 0:
        task_files = task_files[: args.max_files]

    if not task_files:
        print(f"No zero-shot task files found under: {zeroshot_root}")
        return 1

    records: list[dict] = []
    total = len(task_files)
    w = len(str(total))
    matched_idx = 0
    for task_path in task_files:
        payload = read_json(task_path)
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            continue

        dataset_variant = str(metadata.get("dataset_variant", "")).strip()
        pattern_id = str(metadata.get("pattern_id", "")).strip()
        prompting_condition = str(metadata.get("prompting_condition", "")).strip()
        if dataset_filter and dataset_variant not in dataset_filter:
            continue
        if rule_filter and pattern_id not in rule_filter:
            continue

        matched_idx += 1
        record = convert_one(
            task_path=task_path,
            payload=payload,
            output_root=output_root,
            slug=slug,
            api_model=api_model,
            include_system=args.include_system,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
        records.append(record)

        label = f"{prompting_condition}/{dataset_variant}/{pattern_id}"
        status = "skipped (exists)" if record["status"] == "skipped_exists" else "written"
        print(f"[{matched_idx:{w}}] {label:<40}  {record['count']:>5} requests  {status}")

    if not records:
        print("No files matched the filters.")
        return 1

    n_written = sum(1 for r in records if r["status"] == "written")
    n_skipped = sum(1 for r in records if r["status"] == "skipped_exists")
    parts = [f"{n_written} written"]
    if n_skipped:
        parts.append(f"{n_skipped} skipped")
    print(f"Total: {len(records)} files ({', '.join(parts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
