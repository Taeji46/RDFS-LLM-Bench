"""Aggregate per-entry eval results into a flat CSV for analysis.

Reads eval JSONL files from:
  data/llm-eval/eval/{response_type}/{model}/{op}/{dataset}/{n-rule}/
    eval__{model}__{op}__{dataset}__{rule}__n{N}__...__{run_id}.jsonl

Aggregates across ALL response types (openai-batch, sequential, etc.)
and writes one flat CSV:
  data/llm-eval/reports/scores.csv

Columns:
  model, prompting_condition, dataset_variant, pattern_id, n_rule,
  n_total, n_correct, accuracy,
  precision_triple, recall_triple, f1_triple,
  [precision_rule, recall_rule, f1_rule]  -- only for ARP-full/ARP-name
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from statistics import mean

THIS_FILE = Path(__file__).resolve()
LLM_EVAL_DIR = THIS_FILE.parents[1]
PROJECT_ROOT = THIS_FILE.parents[3]
sys.path.insert(0, str(LLM_EVAL_DIR))

from shared.io import read_jsonl

DEFAULT_EVAL_ROOT    = PROJECT_ROOT / "data" / "llm-eval" / "eval"
DEFAULT_REPORT_ROOT  = PROJECT_ROOT / "data" / "llm-eval" / "reports"


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _csv_items(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


def _expand_rules(pattern_id: str) -> list[str]:
    """Expand composite pattern_id into constituent rules.

    Examples:
      "rdfs2"    -> ["rdfs2"]
      "rdfs2_3"  -> ["rdfs2", "rdfs3"]
      "rdfs9_11" -> ["rdfs9", "rdfs11"]
    """
    import re
    m = re.match(r'^(rdfs)(\d+)((?:_\d+)*)$', pattern_id)
    if not m:
        return [pattern_id]
    prefix, first, rest = m.group(1), m.group(2), m.group(3)
    rules = [f"{prefix}{first}"]
    for num in rest.lstrip("_").split("_"):
        if num:
            rules.append(f"{prefix}{num}")
    return rules


def _parse_eval_filename(stem: str) -> dict | None:
    """Parse eval-{mode}__{model}__{op}__{dataset}__{rule}__n{N}__... stem.

    Returns dict with model, prompting_condition, dataset_variant, pattern_id, rules, n_rule,
    or None if unparseable.
    """
    import re as _re
    m = _re.match(r'^eval(?:-\w+)?__', stem)
    if not m:
        return None
    body = stem[m.end():]
    fields = body.split("__")
    if len(fields) < 4:
        return None
    model          = fields[0]
    prompting_condition = fields[1]
    dataset_variant   = fields[2]
    pattern_id        = fields[3]
    rules          = _expand_rules(pattern_id)
    n_rule         = len(rules)
    op_parts       = prompting_condition.split("-", 1)
    presented_rule_type      = op_parts[0] if len(op_parts) == 2 else prompting_condition
    rule_format      = op_parts[1] if len(op_parts) == 2 else ""
    return {
        "model":            model,
        "prompting_condition":   prompting_condition,
        "presented_rule_type": presented_rule_type,
        "rule_format":        rule_format,
        "dataset_variant":     dataset_variant,
        "pattern_id":          pattern_id,
        "rules":            ",".join(rules),
        "n_rule":           n_rule,
    }


def aggregate_file(eval_path: Path) -> dict | None:
    """Aggregate one eval JSONL into a single summary row."""
    info = _parse_eval_filename(eval_path.stem)
    if info is None:
        return None

    rows = read_jsonl(eval_path)
    if not rows:
        return None

    n_total   = len(rows)
    n_correct = sum(1 for r in rows if r.get("overall_ok"))

    avg = lambda key: round(mean(r[key] for r in rows if key in r), 6)

    record: dict = {
        **info,
        "n_total":          n_total,
        "n_correct":        n_correct,
        "accuracy":         round(n_correct / n_total, 6) if n_total else 0.0,
        "precision_triple": avg("precision_triple"),
        "recall_triple":    avg("recall_triple"),
        "f1_triple":        avg("f1_triple"),
    }

    # Rule metrics present only for ARP-full / ARP-name
    if "precision_rule" in rows[0]:
        record["precision_rule"] = avg("precision_rule")
        record["recall_rule"]    = avg("recall_rule")
        record["f1_rule"]        = avg("f1_rule")
    else:
        record["precision_rule"] = ""
        record["recall_rule"]    = ""
        record["f1_rule"]        = ""

    return record


FIELDNAMES = [
    "model", "prompting_condition", "presented_rule_type", "rule_format",
    "dataset_variant", "pattern_id", "rules", "n_rule",
    "n_total", "n_correct", "accuracy",
    "precision_triple", "recall_triple", "f1_triple",
    "precision_rule", "recall_rule", "f1_rule",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate eval JSONL files into a flat CSV."
    )
    parser.add_argument("--mode", type=str, default="strict",
                        choices=["strict", "flex"],
                        help="Evaluation mode (default: strict)")
    parser.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--response-types", type=str, default="",
                        help="Comma-separated response types to include (default: all)")
    parser.add_argument("--models", type=str, default="",
                        help="Comma-separated model names to filter")
    parser.add_argument("--prompting-conditions", type=str, default="")
    parser.add_argument("--dataset-variants", type=str, default="")
    parser.add_argument("--patterns", type=str, default="")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    eval_root   = args.eval_root.resolve() / args.mode
    report_root = args.report_root.resolve() / args.mode

    # Determine which response-type subdirs to scan
    rt_filter = set(_csv_items(args.response_types))
    if rt_filter:
        scan_roots = [eval_root / rt for rt in sorted(rt_filter)]
    else:
        scan_roots = sorted(p for p in eval_root.iterdir() if p.is_dir()) if eval_root.exists() else []

    if not scan_roots:
        print(f"No eval directories found under: {_relpath(eval_root)}")
        return 1

    model_filter = set(_csv_items(args.models))
    op_filter    = set(_csv_items(args.prompting_conditions))
    ds_filter    = set(_csv_items(args.dataset_variants))
    rule_filter  = set(_csv_items(args.patterns))

    mode = args.mode
    eval_glob = f"eval-{mode}__*.jsonl"

    eval_files: list[Path] = []
    for scan_root in scan_roots:
        if scan_root.exists():
            eval_files.extend(scan_root.rglob(eval_glob))
    eval_files = sorted(set(eval_files))

    if not eval_files:
        print(f"No eval files found under: {_relpath(eval_root)}")
        return 1

    def _matches(p: Path) -> bool:
        import re as _re
        m_prefix = _re.match(r'^eval(?:-\w+)?__', p.stem)
        if not m_prefix:
            return False
        fields = p.stem[m_prefix.end():].split("__")
        if len(fields) < 4:
            return False
        m, op, ds, rule = fields[0], fields[1], fields[2], fields[3]
        if model_filter and m    not in model_filter: return False
        if op_filter    and op   not in op_filter:    return False
        if ds_filter    and ds   not in ds_filter:    return False
        if rule_filter  and rule not in rule_filter:  return False
        return True

    eval_files = [p for p in eval_files if _matches(p)]
    if not eval_files:
        print("No eval files matched the filters.")
        return 1

    out_path = report_root / f"scores-{mode}.csv"
    if out_path.exists() and not args.overwrite:
        print(f"Output already exists (use --overwrite): {_relpath(out_path)}")
        return 1

    records: list[dict] = []
    n_error = 0
    for p in eval_files:
        rec = aggregate_file(p)
        if rec is None:
            n_error += 1
        else:
            records.append(rec)

    if not records:
        print("No records aggregated.")
        return 1

    # Sort: model, prompting_condition, dataset_variant, pattern_id
    records.sort(key=lambda r: (r["model"], r["prompting_condition"], r["dataset_variant"], r["pattern_id"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)

    print(f"Written {len(records)} rows -> {_relpath(out_path)}")
    if n_error:
        print(f"  ({n_error} files skipped due to errors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
