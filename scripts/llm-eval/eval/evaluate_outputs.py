"""Evaluate LLM response files against expected outputs.

Reads responses from:
  data/llm-eval/responses/{openai-batch,sequential}/{model}/{op}/{dataset}/{n-rule}/
    response__{model}__{op}__{dataset}__{rule}__n{N}__...__{run_id}.jsonl

Reads task (expected outputs) from:
  data/llm-eval/tasks/zeroshot/{op}/{dataset}/{n-rule}/
    task__{op}__{dataset}__{rule}__n{N}__....json

Saves per-entry eval results to:
  data/llm-eval/eval/{response_type}/{model}/{op}/{dataset}/{n-rule}/
    eval__{model}__{op}__{dataset}__{rule}__n{N}__...__{run_id}.jsonl

Supported response formats:
  - openai-batch : {"custom_id": "...", "response": {"body": {"choices": [...]}}}
  - sequential   : {"id": "...", "response": "..."}
                   {"id": "...", "choices": [{"message": {"content": "..."}}]}
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_json, write_jsonl
from shared.eval_utils import (
    extract_rdf_candidates,
    extract_rdf_triples,
    extract_used_rules,
    compute_set_metrics,
    compute_flex_metrics_with_filtered,
    ARP_RULE_EVAL_OPS,
)
from shared.numeric import metric_to_str

DEFAULT_RESPONSE_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "responses"
DEFAULT_TASK_ROOT     = PROJECT_ROOT / "data" / "llm-eval" / "tasks" / "zeroshot"
DEFAULT_EVAL_ROOT     = PROJECT_ROOT / "data" / "llm-eval" / "eval"


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _extract_output(entry: dict) -> str:
    """Extract model text output from a response entry (batch or sequential)."""
    # OpenAI batch format
    try:
        content = entry["response"]["body"]["choices"][0]["message"]["content"]
        if content is not None:
            return str(content)
    except (KeyError, IndexError, TypeError):
        pass
    # Sequential OpenAI-compat format
    try:
        content = entry["choices"][0]["message"]["content"]
        if content is not None:
            return str(content)
    except (KeyError, IndexError, TypeError):
        pass
    # Simple sequential format
    resp = entry.get("response", "")
    if isinstance(resp, str):
        return resp
    return ""


def _task_id(entry: dict) -> str:
    """Extract task_id from a response entry."""
    return str(entry.get("custom_id") or entry.get("id") or "")


# ---------------------------------------------------------------------------
# Task file lookup
# ---------------------------------------------------------------------------

def _build_task_index(task_root: Path) -> dict[str, Path]:
    """Build index: stem_without_prefix -> task path.

    Key is the part after "task__", e.g. "NRP-full__gs__rdfs2_3__n400__f-xxx__b-yyy"
    """
    index: dict[str, Path] = {}
    for p in task_root.rglob("task__*.json"):
        key = p.stem[len("task__"):]
        index[key] = p
    return index


def _task_key_from_response(resp_path: Path) -> str:
    """Derive task lookup key from response filename.

    Handles both old and new filename formats:
      Old: response__{model}__{op}__{dataset}__{rule}__n{N}__[f-uid__]b-uid__{hex}
      New: response__{model}__{op}__{dataset}__{rule}__n{N}__[f-uid__]b-uid__batch_{hex}__{ts}

    → {op}__{dataset}__{rule}__n{N}__[f-uid__]b-uid
    """
    import re as _re
    stem = resp_path.stem  # response__...
    body = stem[len("response__"):]   # model__op__dataset__rule__nN__...__run_id
    fields = body.split("__")
    # Drop leading model field
    fields = fields[1:]
    # Drop trailing timestamp (14-digit YYYYMMDDHHMMSS)
    if fields and _re.fullmatch(r'\d{14}', fields[-1]):
        fields = fields[:-1]
    # Drop trailing batch_id (starts with "batch_" or is a plain hex string)
    if fields and (_re.fullmatch(r'batch_[0-9a-f]+', fields[-1]) or _re.fullmatch(r'[0-9a-f]{16,}', fields[-1])):
        fields = fields[:-1]
    return "__".join(fields)


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_one(
    resp_path: Path,
    scan_root: Path,
    task_index: dict[str, Path],
    eval_root: Path,
    overwrite: bool,
    verbose: bool,
    mode: str = "strict",
) -> str:
    """Returns: written | skipped_exists | no_task | error

    eval path mirrors scan_root structure under eval_root:
      scan_root = responses/openai-batch/
      eval_root = eval/
      resp_path = responses/openai-batch/gpt-4o/.../response__X.jsonl
      eval_path = eval/openai-batch/gpt-4o/.../eval__X.jsonl
    """
    task_key = _task_key_from_response(resp_path)
    task_path = task_index.get(task_key)
    if task_path is None:
        if verbose:
            print(f"  [WARN] no task file for key: {task_key}")
        return "no_task"

    # Derive eval path
    rel = resp_path.relative_to(scan_root.parent)  # openai-batch/gpt-4o/.../response__X.jsonl
    eval_name = resp_path.name.replace("response__", f"eval-{mode}__", 1)
    eval_path = eval_root / rel.parent / eval_name

    if eval_path.exists() and not overwrite:
        if verbose:
            print(f"  SKIP (exists): {_relpath(eval_path)}")
        return "skipped_exists"

    # Load task
    task_payload = read_json(task_path)
    if not isinstance(task_payload, dict):
        return "error"

    task_map: dict[str, dict] = {
        str(t["task_id"]): t
        for t in task_payload.get("tasks", [])
        if isinstance(t, dict)
    }

    metadata = task_payload.get("metadata", {})
    prompting_condition: str = str(metadata.get("prompting_condition", ""))
    rules: list[str] = metadata.get("rules", [])
    do_rule_eval = prompting_condition in ARP_RULE_EVAL_OPS

    # Load response entries
    entries: list[dict] = []
    try:
        with resp_path.open(encoding="utf-8") as fh:
            import json
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        if verbose:
            print(f"  [ERROR] reading {resp_path.name}: {e}")
        return "error"

    # Evaluate
    results: list[dict] = []
    target_empty_count = 0
    for entry in entries:
        tid = _task_id(entry)
        task = task_map.get(tid, {})

        output_text = _extract_output(entry)
        premise     = str(task.get("premise_knowledge", ""))
        expected_out = str(task.get("expected_output", ""))

        premise_triples  = extract_rdf_triples(premise)
        expected_triples = extract_rdf_triples(expected_out)
        target_triples   = expected_triples - premise_triples
        target_empty     = len(target_triples) == 0
        if target_empty:
            target_empty_count += 1

        if mode == "flex":
            model_candidates = extract_rdf_candidates(output_text)
            try:
                (
                    p_t,
                    r_t,
                    f1_t,
                    premise_filtered_candidates,
                    scored_candidates,
                    matched_target_triples,
                    unmatched_candidates,
                ) = compute_flex_metrics_with_filtered(
                    target_triples, model_candidates, premise_triples
                )
            except ValueError as exc:
                raise ValueError(f"task {tid}: {exc}") from exc
        else:
            raw_model_triples = extract_rdf_triples(output_text)
            filtered_triples  = raw_model_triples - premise_triples
            p_t, r_t, f1_t = compute_set_metrics(target_triples, filtered_triples)

        triple_ok = (p_t == 1 and r_t == 1)

        row: dict = {
            "task_id":          tid,
            "premise_knowledge": premise,
            "expected_output":  expected_out,
            "model_output":     output_text,
            "expected_triples": sorted(expected_triples),
            "target_triples":   sorted(target_triples),
            "target_empty":     target_empty,
            "precision_triple": metric_to_str(p_t),
            "recall_triple":    metric_to_str(r_t),
            "f1_triple":        metric_to_str(f1_t),
            "triple_ok":        triple_ok,
        }

        if mode == "flex":
            row.update({
                "premise_filtered_candidates": premise_filtered_candidates,
                "scored_candidates": scored_candidates,
                "matched_target_triples": sorted(matched_target_triples),
                "unmatched_candidates": sorted(unmatched_candidates),
            })
        else:
            row["filtered_triples"] = sorted(filtered_triples)

        if do_rule_eval:
            model_rules = extract_used_rules(output_text)
            p_r, r_r, f1_r = compute_set_metrics(rules, model_rules)
            rule_ok = (p_r == 1 and r_r == 1)
            row.update({
                "expected_rules":   rules,
                "model_rules":      model_rules,
                "precision_rule":   metric_to_str(p_r),
                "recall_rule":      metric_to_str(r_r),
                "f1_rule":          metric_to_str(f1_r),
                "rule_ok":          rule_ok,
            })
            row["overall_ok"] = triple_ok and rule_ok
        else:
            row["overall_ok"] = triple_ok

        results.append(row)

    if target_empty_count:
        n = len(results)
        print(f"  [ERROR] {target_empty_count}/{n} rows have empty target_triples; eval file was not written")
        return "error"

    eval_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(eval_path, results)

    if verbose:
        n = len(results)
        ok = sum(1 for r in results if r["overall_ok"])
        print(f"  -> {_relpath(eval_path)}  ({ok}/{n} correct)")

    return "written"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _csv_items(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate LLM response files against expected outputs."
    )
    parser.add_argument("--response-root", type=Path, default=DEFAULT_RESPONSE_ROOT,
                        help="Root of response files (default: data/llm-eval/responses)")
    parser.add_argument("--response-type", type=str, default="",
                        help="Sub-directory under response-root (e.g. openai-batch, sequential). Default: all sub-directories")
    parser.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    parser.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    parser.add_argument("--models", type=str, default="",
                        help="Comma-separated model names to filter")
    parser.add_argument("--prompting-conditions", type=str, default="",
                        help="Comma-separated prompting conditions")
    parser.add_argument("--dataset-variants", type=str, default="",
                        help="Comma-separated dataset variants")
    parser.add_argument("--patterns", type=str, default="",
                        help="Comma-separated pattern ids")
    parser.add_argument("--mode", type=str, default="strict",
                        choices=["strict", "flex"],
                        help="Evaluation mode: strict=exact match, flex=order-based match (default: strict)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing eval files")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-file details")
    args = parser.parse_args()

    response_root  = args.response_root.resolve()
    response_type  = args.response_type
    task_root      = args.task_root.resolve()
    mode           = args.mode
    # strict → data/llm-eval/eval/strict/
    # flex → data/llm-eval/eval/flex/
    eval_root      = args.eval_root.resolve() / mode

    # Determine which sub-directories to scan
    if response_type:
        scan_roots = [response_root / response_type]
    else:
        if not response_root.exists():
            print(f"Response root not found: {_relpath(response_root)}")
            return 1
        scan_roots = sorted(d for d in response_root.iterdir() if d.is_dir())

    for sr in scan_roots:
        if not sr.exists():
            print(f"Response directory not found: {_relpath(sr)}")
            return 1

    model_filter   = set(_csv_items(args.models))
    op_filter      = set(_csv_items(args.prompting_conditions))
    ds_filter      = set(_csv_items(args.dataset_variants))
    rule_filter    = set(_csv_items(args.patterns))

    # Apply filters using filename fields:
    # response__{model}__{op}__{dataset}__{rule}__...
    def _matches(p: Path) -> bool:
        fields = p.stem[len("response__"):].split("__")
        if len(fields) < 4:
            return False
        m_model, m_op, m_ds, m_rule = fields[0], fields[1], fields[2], fields[3]
        if model_filter  and m_model not in model_filter:  return False
        if op_filter     and m_op    not in op_filter:     return False
        if ds_filter     and m_ds    not in ds_filter:     return False
        if rule_filter   and m_rule  not in rule_filter:   return False
        return True

    # Collect (resp_path, scan_root) pairs across all scan roots
    resp_pairs: list[tuple[Path, Path]] = []
    for sr in scan_roots:
        for p in sorted(sr.rglob("response__*.jsonl")):
            if _matches(p):
                resp_pairs.append((p, sr))

    if not resp_pairs:
        labels = ", ".join(_relpath(sr) for sr in scan_roots)
        print(f"No response files found under: {labels}")
        return 1

    print(f"Building task index from: {_relpath(task_root)}")
    task_index = _build_task_index(task_root)
    print(f"  {len(task_index)} task files indexed")
    print()

    total = len(resp_pairs)
    w = len(str(total))
    n_written = n_skipped = n_no_task = n_error = 0

    for idx, (resp_path, scan_root) in enumerate(resp_pairs, start=1):
        label = resp_path.stem[len("response__"):]
        print(f"[{idx:{w}}/{total}] {label}")

        result = evaluate_one(
            resp_path=resp_path,
            scan_root=scan_root,
            task_index=task_index,
            eval_root=eval_root,
            overwrite=args.overwrite,
            verbose=args.verbose,
            mode=mode,
        )

        if result == "written":
            n_written += 1
        elif result == "skipped_exists":
            n_skipped += 1
            print("  skipped (exists)")
        elif result == "no_task":
            n_no_task += 1
            print("  [WARN] no matching task file")
        else:
            n_error += 1
            print("  [ERROR]")

    print()
    parts = [f"{n_written} written"]
    if n_skipped:  parts.append(f"{n_skipped} skipped")
    if n_no_task:  parts.append(f"{n_no_task} no-task")
    if n_error:    parts.append(f"{n_error} errors")
    print(f"Total: {total} files ({', '.join(parts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
