"""Build zero-shot LLM-eval task files from benchmark datasets.

Input:
  data/datasets/{dataset_type}/{n-rule}/dataset__*.json

Output:
  data/llm-eval/tasks/zeroshot/{operation_type}/{dataset_type}/{n-rule}/task__*.json
"""

from __future__ import annotations

import argparse
from datetime import datetime
import re
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_json, write_json
from shared.prompt_builder import build_prompt, normalize_operation_type, get_template_hash
from shared.rule_defs import DEFAULT_SYSTEM_PROMPT, OPERATION_TYPES

DEFAULT_DATASET_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "tasks" / "zeroshot"

# Valid operation types per rule count.
# ESRA: single-rule application — full/name only meaningful for 1-rule (standard rule names)
# EMRA: multi-rule application  — requires 2+ rules
# SRA:  selective application   — always valid
_VALID_OPERATION_TYPES: dict[int, set[str]] = {
    1: {"ESRA-full", "ESRA-name", "ESRA-def", "SRA-full", "SRA-name", "SRA-def"},
    2: {"ESRA-def", "EMRA-full", "EMRA-name", "EMRA-def", "SRA-full", "SRA-name", "SRA-def"},
    3: {"ESRA-def", "EMRA-full", "EMRA-name", "EMRA-def", "SRA-full", "SRA-name", "SRA-def"},
}


def is_valid_operation_type(operation_type: str, rule_count: int) -> bool:
    return operation_type in _VALID_OPERATION_TYPES.get(rule_count, set())


def _csv_items(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _resolve_operation_types(raw: str) -> list[str]:
    if not raw.strip():
        return list(OPERATION_TYPES)

    operation_types: list[str] = []
    for item in _csv_items(raw):
        op_type = normalize_operation_type(item)
        if op_type not in operation_types:
            operation_types.append(op_type)
    return operation_types


def _rule_dir_from_rule(rule_id: str) -> str:
    return f"{rule_id.count('_') + 1}-rule"


def _available_dataset_types(dataset_root: Path) -> list[str]:
    if not dataset_root.exists():
        return []
    return sorted(p.name for p in dataset_root.iterdir() if p.is_dir())


def _iter_dataset_files(dataset_root: Path, dataset_types: list[str]) -> list[Path]:
    files: list[Path] = []
    for dataset_type in dataset_types:
        base = dataset_root / dataset_type
        if not base.exists():
            print(f"WARNING: dataset type directory does not exist: {base}")
            continue
        files.extend(sorted(base.rglob("dataset__*.json")))
    return files


def _required_str(metadata: dict, key: str, dataset_path: Path) -> str:
    value = str(metadata.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing metadata.{key}: {dataset_path}")
    return value


def _required_rules(metadata: dict, dataset_path: Path) -> list[str]:
    raw = metadata.get("rules")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"missing metadata.rules: {dataset_path}")

    rules: list[str] = []
    for item in raw:
        rule = str(item).strip()
        if not re.fullmatch(r"rdfs\d+", rule):
            raise ValueError(f"invalid rule name in metadata.rules: {dataset_path}: {item}")
        rules.append(rule)
    return rules



def _build_tasks(
    entries: list[dict],
    operation_type: str,
    rule_id: str,
    entry_limit: int,
) -> list[dict]:
    if entry_limit > 0:
        entries = entries[:entry_limit]

    tasks: list[dict] = []
    for idx, entry in enumerate(entries, start=1):
        premise_knowledge = str(entry.get("premise_knowledge", "")).strip()
        expected_output = str(entry.get("expected_output", "")).strip()

        if not premise_knowledge:
            print(f"  WARNING: skip empty premise_knowledge at entry index {idx-1}")
            continue

        prompt = build_prompt(
            operation_type=operation_type,
            premise_knowledge=premise_knowledge,
            rule_id=rule_id,
        )

        tasks.append(
            {
                "task_id": f"request-{idx}",
                "source_index": idx - 1,
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "user_prompt": prompt,
                "premise_knowledge": premise_knowledge,
                "expected_output": expected_output,
            }
        )
    return tasks


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def build_zeroshot_tasks(
    dataset_path: Path,
    output_root: Path,
    operation_types: list[str],
    entry_limit: int,
    overwrite: bool,
    verbose: bool = False,
) -> list[dict]:
    payload = read_json(dataset_path)
    if not isinstance(payload, dict):
        raise ValueError(f"dataset payload must be dict: {dataset_path}")

    metadata = payload.get("metadata", {})
    entries = payload.get("entries", [])
    if not isinstance(metadata, dict) or not isinstance(entries, list):
        raise ValueError(f"invalid dataset structure: {dataset_path}")

    dataset_type = _required_str(metadata, "dataset_type", dataset_path)
    rule_id = _required_str(metadata, "rule_id", dataset_path)
    rules = _required_rules(metadata, dataset_path)
    source_uid: str | None = metadata.get("fetch_uid") or None
    build_uid = _required_str(metadata, "build_uid", dataset_path)
    rule_dir = _rule_dir_from_rule(rule_id)
    source_dataset = _relpath(dataset_path)

    rule_count = len(rules)
    records: list[dict] = []
    for operation_type in operation_types:
        if not is_valid_operation_type(operation_type, rule_count):
            records.append({
                "operation_type": operation_type,
                "dataset_type": dataset_type,
                "rule_id": rule_id,
                "build_uid": build_uid,
                "task_count": 0,
                "source_dataset": source_dataset,
                "zeroshot_task_file": None,
                "status": "skipped_invalid",
            })
            continue

        tasks = _build_tasks(entries, operation_type=operation_type, rule_id=rule_id, entry_limit=entry_limit)
        template_uid = get_template_hash(operation_type)

        out_dir = output_root / operation_type / dataset_type / rule_dir
        if source_uid is not None:
            out_name = f"task__{operation_type}__{dataset_type}__{rule_id}__n{len(tasks)}__{source_uid}__{build_uid}__{template_uid}.json"
        else:
            out_name = f"task__{operation_type}__{dataset_type}__{rule_id}__n{len(tasks)}__{build_uid}__{template_uid}.json"
        out_path = out_dir / out_name

        if out_path.exists() and not overwrite:
            if verbose:
                print(f"SKIP (exists): {out_path}")
            records.append(
                {
                    "operation_type": operation_type,
                    "dataset_type": dataset_type,
                    "rule_id": rule_id,
                    "build_uid": build_uid,
                    "task_count": len(tasks),
                    "source_dataset": source_dataset,
                    "zeroshot_task_file": _relpath(out_path),
                    "status": "skipped_exists",
                }
            )
            continue

        task_metadata: dict = {
            "operation_type": operation_type,
            "dataset_type": dataset_type,
            "rule_id": rule_id,
            "rules": rules,
            "rule_dir": rule_dir,
        }
        if source_uid is not None:
            task_metadata["source_uid"] = source_uid
        task_metadata["build_uid"] = build_uid
        task_metadata["template_uid"] = template_uid
        task_metadata["task_count"] = len(tasks)
        task_metadata["source_dataset"] = source_dataset
        task_metadata["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        task_payload = {"metadata": task_metadata, "tasks": tasks}

        write_json(out_path, task_payload, indent=2)
        if verbose:
            print(f"Saved {len(tasks)} tasks -> {out_path}")

        records.append(
            {
                "operation_type": operation_type,
                "dataset_type": dataset_type,
                "rule_id": rule_id,
                "build_uid": build_uid,
                "task_count": len(tasks),
                "source_dataset": source_dataset,
                "zeroshot_task_file": _relpath(out_path),
                "status": "written",
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build zero-shot llm-eval task files from datasets.")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dataset-types", type=str, default="", help="Comma-separated dataset types (e.g. rk,ls,gs)")
    parser.add_argument("--rules", type=str, default="", help="Comma-separated rule ids (e.g. rdfs2,rdfs2_3)")
    parser.add_argument("--operation-types", type=str, default=",".join(OPERATION_TYPES), help="Comma-separated inference operation types (e.g. ESRA-full,EMRA-name)")
    parser.add_argument("--max-files", type=int, default=0, help="Debug option: process only first N dataset files")
    parser.add_argument("--entry-limit", type=int, default=0, help="Debug option: keep only first N entries per dataset")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing zero-shot task files")
    parser.add_argument("--verbose", action="store_true", help="Print each saved file path")
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()

    dataset_types = _csv_items(args.dataset_types) or _available_dataset_types(dataset_root)
    if not dataset_types:
        print(f"No dataset types found under: {dataset_root}")
        return 1

    operation_types = _resolve_operation_types(args.operation_types)
    rule_filter = set(_csv_items(args.rules))

    dataset_files = _iter_dataset_files(dataset_root, dataset_types)
    if rule_filter:
        filtered: list[Path] = []
        for path in dataset_files:
            payload = read_json(path)
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            if not isinstance(metadata, dict):
                continue
            rule_id = str(metadata.get("rule_id", "")).strip()
            if rule_id and rule_id in rule_filter:
                filtered.append(path)
        dataset_files = filtered

    if args.max_files > 0:
        dataset_files = dataset_files[: args.max_files]

    if not dataset_files:
        print("No dataset files matched the conditions.")
        return 1

    total = len(dataset_files)
    print(f"Dataset files    : {total}")
    print(f"Dataset types    : {dataset_types}")
    print(f"Operation types  : {operation_types}")
    print("-" * 60)

    total_task_files = 0
    total_tasks = 0

    for idx, dataset_path in enumerate(dataset_files, start=1):
        records = build_zeroshot_tasks(
            dataset_path=dataset_path,
            output_root=output_root,
            operation_types=operation_types,
            entry_limit=args.entry_limit,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
        written = [r for r in records if r["status"] == "written"]
        skipped_exists = [r for r in records if r["status"] == "skipped_exists"]
        skipped_invalid = [r for r in records if r["status"] == "skipped_invalid"]
        file_tasks = sum(r["task_count"] for r in written)
        total_task_files += len(written)
        total_tasks += file_tasks

        payload = read_json(dataset_path)
        meta = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        label = f"{meta.get('dataset_type', '?')}/{meta.get('rule_id', '?')}"
        parts = [f"{len(written)} written"]
        if skipped_exists:
            parts.append(f"{len(skipped_exists)} exists")
        w = len(str(total))
        print(f"[{idx:{w}}/{total}] {label:<20}  {file_tasks:>5} tasks  ({', '.join(parts)})")

    print("-" * 60)
    print(f"Total: {total_task_files} task files, {total_tasks} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
