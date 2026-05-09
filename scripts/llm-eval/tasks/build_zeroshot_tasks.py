"""Build zero-shot LLM-eval task files from benchmark datasets.

Input:
  data/datasets/{dataset_variant}/{n-rule}/dataset__*.json

Output:
  data/llm-eval/tasks/zeroshot/{prompting_condition}/{dataset_variant}/{n-rule}/task__*.json
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
from shared.prompt_builder import build_prompt, normalize_prompting_condition, get_template_hash
from shared.rule_defs import DEFAULT_SYSTEM_PROMPT, PROMPTING_CONDITIONS

DEFAULT_DATASET_ROOT = PROJECT_ROOT / "data" / "datasets"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "tasks" / "zeroshot"

# Valid prompting conditions per rule count.
# NRP: necessary rule presentation — all n valid
# ARP: all-rule presentation      — always valid
_VALID_PROMPTING_CONDITIONS: dict[int, set[str]] = {
    1: {"NRP-full", "NRP-name", "NRP-def", "ARP-full", "ARP-name", "ARP-def"},
    2: {"NRP-full", "NRP-name", "NRP-def", "ARP-full", "ARP-name", "ARP-def"},
    3: {"NRP-full", "NRP-name", "NRP-def", "ARP-full", "ARP-name", "ARP-def"},
}


def is_valid_prompting_condition(prompting_condition: str, rule_count: int) -> bool:
    return prompting_condition in _VALID_PROMPTING_CONDITIONS.get(rule_count, set())


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


def _rule_dir_from_rule(pattern_id: str) -> str:
    return f"{pattern_id.count('_') + 1}-rule"


def _available_dataset_variants(dataset_root: Path) -> list[str]:
    if not dataset_root.exists():
        return []
    return sorted(p.name for p in dataset_root.iterdir() if p.is_dir())


def _iter_dataset_files(dataset_root: Path, dataset_variants: list[str]) -> list[Path]:
    files: list[Path] = []
    for dataset_variant in dataset_variants:
        base = dataset_root / dataset_variant
        if not base.exists():
            print(f"WARNING: dataset variant directory does not exist: {base}")
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
    prompting_condition: str,
    pattern_id: str,
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
            prompting_condition=prompting_condition,
            premise_knowledge=premise_knowledge,
            pattern_id=pattern_id,
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
    prompting_conditions: list[str],
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

    dataset_variant = _required_str(metadata, "dataset_variant", dataset_path)
    pattern_id = _required_str(metadata, "pattern_id", dataset_path)
    rules = _required_rules(metadata, dataset_path)
    source_uid: str | None = metadata.get("fetch_uid") or None
    build_uid = _required_str(metadata, "build_uid", dataset_path)
    rule_dir = _rule_dir_from_rule(pattern_id)
    source_dataset = _relpath(dataset_path)

    rule_count = len(rules)
    records: list[dict] = []
    for prompting_condition in prompting_conditions:
        if not is_valid_prompting_condition(prompting_condition, rule_count):
            records.append({
                "prompting_condition": prompting_condition,
                "dataset_variant": dataset_variant,
                "pattern_id": pattern_id,
                "build_uid": build_uid,
                "task_count": 0,
                "source_dataset": source_dataset,
                "zeroshot_task_file": None,
                "status": "skipped_invalid",
            })
            continue

        tasks = _build_tasks(entries, prompting_condition=prompting_condition, pattern_id=pattern_id, entry_limit=entry_limit)
        template_uid = get_template_hash(prompting_condition, pattern_id)

        out_dir = output_root / prompting_condition / dataset_variant / rule_dir
        if source_uid is not None:
            out_name = f"task__{prompting_condition}__{dataset_variant}__{pattern_id}__n{len(tasks)}__{source_uid}__{build_uid}__{template_uid}.json"
        else:
            out_name = f"task__{prompting_condition}__{dataset_variant}__{pattern_id}__n{len(tasks)}__{build_uid}__{template_uid}.json"
        out_path = out_dir / out_name

        if out_path.exists() and not overwrite:
            if verbose:
                print(f"SKIP (exists): {out_path}")
            records.append(
                {
                    "prompting_condition": prompting_condition,
                    "dataset_variant": dataset_variant,
                    "pattern_id": pattern_id,
                    "build_uid": build_uid,
                    "task_count": len(tasks),
                    "source_dataset": source_dataset,
                    "zeroshot_task_file": _relpath(out_path),
                    "status": "skipped_exists",
                }
            )
            continue

        task_metadata: dict = {
            "prompting_condition": prompting_condition,
            "dataset_variant": dataset_variant,
            "pattern_id": pattern_id,
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
                "prompting_condition": prompting_condition,
                "dataset_variant": dataset_variant,
                "pattern_id": pattern_id,
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
    parser.add_argument("--dataset-variants", type=str, default="", help="Comma-separated dataset variants (e.g. rk,ls,gs)")
    parser.add_argument("--patterns", type=str, default="", help="Comma-separated pattern ids (e.g. rdfs2,rdfs2_3)")
    parser.add_argument("--prompting-conditions", type=str, default=",".join(PROMPTING_CONDITIONS), help="Comma-separated prompting conditions (e.g. NRP-full,NRP-name)")
    parser.add_argument("--max-files", type=int, default=0, help="Debug option: process only first N dataset files")
    parser.add_argument("--entry-limit", type=int, default=0, help="Debug option: keep only first N entries per dataset")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing zero-shot task files")
    parser.add_argument("--verbose", action="store_true", help="Print each saved file path")
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()

    dataset_variants = _csv_items(args.dataset_variants) or _available_dataset_variants(dataset_root)
    if not dataset_variants:
        print(f"No dataset variants found under: {dataset_root}")
        return 1

    prompting_conditions = _resolve_prompting_conditions(args.prompting_conditions)
    rule_filter = set(_csv_items(args.patterns))

    dataset_files = _iter_dataset_files(dataset_root, dataset_variants)
    if rule_filter:
        filtered: list[Path] = []
        for path in dataset_files:
            payload = read_json(path)
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            if not isinstance(metadata, dict):
                continue
            pattern_id = str(metadata.get("pattern_id", "")).strip()
            if pattern_id and pattern_id in rule_filter:
                filtered.append(path)
        dataset_files = filtered

    if args.max_files > 0:
        dataset_files = dataset_files[: args.max_files]

    if not dataset_files:
        print("No dataset files matched the conditions.")
        return 1

    total = len(dataset_files)
    print(f"Dataset files    : {total}")
    print(f"Dataset variants  : {dataset_variants}")
    print(f"Prompting conditions: {prompting_conditions}")
    print("-" * 60)

    total_task_files = 0
    total_tasks = 0

    for idx, dataset_path in enumerate(dataset_files, start=1):
        records = build_zeroshot_tasks(
            dataset_path=dataset_path,
            output_root=output_root,
            prompting_conditions=prompting_conditions,
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
        label = f"{meta.get('dataset_variant', '?')}/{meta.get('pattern_id', '?')}"
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
