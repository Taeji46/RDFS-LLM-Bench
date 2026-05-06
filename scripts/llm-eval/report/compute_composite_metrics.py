"""Compute composite metrics for LLM RDFS benchmark comparison.

Reads:
  data/llm-eval/reports/scores.csv

Writes:
  data/llm-eval/reports/composite_metrics.csv

Composite metrics (each in [0, 1], higher is better):

Inference ability:
  RI  (Real-world Inference)    : f1_triple on RK, across ESRA/EMRA/SRA × n_rule
  SI  (Structural Inference)    : f1_triple on NS, across ESRA/EMRA/SRA × n_rule

Rule selection ability:
  RRS (Real-world Rule Selection): f1_rule on RK, across SRA-full/SRA-name × n_rule
  SRS (Structural Rule Selection): f1_rule on NS, across SRA-full/SRA-name × n_rule

Robustness:
  VR  (Vocabulary Robustness)   : mean min(1, GSC/NSC) across ESRA/EMRA/SRA × n_rule
  TR  (Token / Naming Robustness): mean min(1, GS/GSC) across ESRA/EMRA/SRA × n_rule

Pre-training knowledge:
  RDI (Rule Definition Independence): mean min(1, name/full) on NS across all 6 combos
    ESRA:1→ESRA-name/ESRA-full, EMRA:2,3→EMRA-name/EMRA-full, SRA:1,2,3→SRA-name/SRA-full
    High RDI ≈ model does not need the rule definition text (pre-training knowledge)
    Low RDI  ≈ model relies on the provided rule definition

Averaging procedure:
  For each of 6 (family × n_rule) combinations:
    (ESRA:1-rule, EMRA:2-rule, EMRA:3-rule, SRA:1-rule, SRA:2-rule, SRA:3-rule)
  compute the mean F1 over all applicable rule_info variants and rule_ids,
  then take the mean of these 6 values.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[3]

DEFAULT_REPORT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "reports"

# Valid (operation_family, n_rule) combinations for averaging
COMBO_KEYS = [
    ("ESRA", 1),
    ("EMRA", 2),
    ("EMRA", 3),
    ("SRA",  1),
    ("SRA",  2),
    ("SRA",  3),
]

# For rule selection metrics, only SRA-full and SRA-name have f1_rule
RULE_EVAL_OP_TYPES = {"SRA-full", "SRA-name"}


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _load_scores(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _float(val: str) -> float | None:
    if val == "" or val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _mean_or_none(values: list[float]) -> float | None:
    valid = [v for v in values if v is not None]
    return mean(valid) if valid else None


def compute_metrics_for_model(records: list[dict]) -> dict[str, float | None]:
    """Compute all 7 composite metrics for one model's records."""

    # Index: (operation_type, dataset_type, rule_id) -> record
    idx: dict[tuple, dict] = {}
    for rec in records:
        key = (rec["operation_type"], rec["dataset_type"], rec["rule_id"])
        idx[key] = rec

    def _f1_triple(op_type: str, ds: str, rule_id: str) -> float | None:
        rec = idx.get((op_type, ds, rule_id))
        return _float(rec["f1_triple"]) if rec else None

    def _f1_rule(op_type: str, ds: str, rule_id: str) -> float | None:
        rec = idx.get((op_type, ds, rule_id))
        if rec is None:
            return None
        v = _float(rec.get("f1_rule", ""))
        return v if v is not None else None

    # Collect all rule_ids per (family, n_rule)
    combo_rules: dict[tuple, set[str]] = defaultdict(set)
    for rec in records:
        family = rec["operation_family"]
        n_rule = int(rec["n_rule"])
        key = (family, n_rule)
        if key in COMBO_KEYS:
            combo_rules[key].add(rec["rule_id"])

    # Full-variant operation type per family (RI/SI/RRS/SRS/VR/TR use full only)
    FULL_OP = {"ESRA": "ESRA-full", "EMRA": "EMRA-full", "SRA": "SRA-full"}

    def _combo_mean_f1(ds: str, metric: str = "triple") -> float | None:
        """Mean over applicable (family × n_rule) combos using full-variant only.

        Returns None if any applicable combo has no data.
        """
        combo_vals: list[float] = []
        for (fam, n_rule) in COMBO_KEYS:
            op = FULL_OP.get(fam)
            if op is None:
                continue
            if metric == "rule" and op not in RULE_EVAL_OP_TYPES:
                continue
            rules = combo_rules.get((fam, n_rule), set())
            cell_vals: list[float] = []
            for rule_id in rules:
                if metric == "triple":
                    v = _f1_triple(op, ds, rule_id)
                else:
                    v = _f1_rule(op, ds, rule_id)
                if v is not None:
                    cell_vals.append(v)
            if not cell_vals:
                return None
            combo_vals.append(mean(cell_vals))
        return mean(combo_vals) if combo_vals else None

    # RI / SI
    ri = _combo_mean_f1("rk", "triple")
    si = _combo_mean_f1("ns", "triple")

    # RRS / SRS
    rrs = _combo_mean_f1("rk", "rule")
    srs = _combo_mean_f1("ns", "rule")

    def _robustness_mean(num_ds: str, den_ds: str) -> float | None:
        """Mean min(1, num/den) over 6 (family × n_rule) combos using full-variant only.

        Returns None if any combo has no data.
        """
        combo_vals: list[float] = []
        for (fam, n_rule) in COMBO_KEYS:
            op = FULL_OP.get(fam)
            if op is None:
                continue
            rules = combo_rules.get((fam, n_rule), set())
            cell_vals: list[float] = []
            for rule_id in rules:
                num = _f1_triple(op, num_ds, rule_id)
                den = _f1_triple(op, den_ds, rule_id)
                if num is not None and den is not None and den > 0:
                    cell_vals.append(min(1.0, num / den))
            if not cell_vals:
                return None
            combo_vals.append(mean(cell_vals))
        return mean(combo_vals) if combo_vals else None

    # VR: min(1, GSC/NSC)
    vr = _robustness_mean("gsc", "nsc")

    # TR: min(1, GS/GSC)
    tr = _robustness_mean("gs", "gsc")

    # RDI: mean min(1, name/full) on NS across all 6 (family × n_rule) combos
    # ESRA:1 → ESRA-name/ESRA-full, EMRA:2,3 → EMRA-name/EMRA-full, SRA:1,2,3 → SRA-name/SRA-full
    NAME_OP = {"ESRA": "ESRA-name", "EMRA": "EMRA-name", "SRA": "SRA-name"}
    rdi_combo_vals: list[float] = []
    rdi_ok = True
    for (fam, n_rule) in COMBO_KEYS:
        name_op = NAME_OP.get(fam)
        full_op = FULL_OP.get(fam)
        if name_op is None or full_op is None:
            continue
        rules = combo_rules.get((fam, n_rule), set())
        cell_vals: list[float] = []
        for rule_id in rules:
            name_v = _f1_triple(name_op, "ns", rule_id)
            full_v = _f1_triple(full_op, "ns", rule_id)
            if name_v is not None and full_v is not None and full_v > 0:
                cell_vals.append(min(1.0, name_v / full_v))
        if not cell_vals:
            rdi_ok = False
            break
        rdi_combo_vals.append(mean(cell_vals))
    rdi = mean(rdi_combo_vals) if (rdi_ok and rdi_combo_vals) else None

    return {
        "RI":  ri,
        "SI":  si,
        "RRS": rrs,
        "SRS": srs,
        "VR":  vr,
        "TR":  tr,
        "RDI": rdi,
    }


FIELDNAMES = ["model", "RI", "SI", "RRS", "SRS", "VR", "TR", "RDI"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute composite metrics from scores.csv."
    )
    parser.add_argument("--mode", type=str, default="strict",
                        choices=["strict", "flex"],
                        help="Evaluation mode (default: strict)")
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    mode        = args.mode
    report_root = args.report_root.resolve() / mode
    csv_path    = report_root / f"scores-{mode}.csv"
    out_path    = report_root / f"composite_metrics-{mode}.csv"

    if not csv_path.exists():
        print(f"scores.csv not found: {_relpath(csv_path)}")
        print("Run aggregate_scores.py first.")
        return 1

    if out_path.exists() and not args.overwrite:
        print(f"Output already exists (use --overwrite): {_relpath(out_path)}")
        return 1

    records = _load_scores(csv_path)
    if not records:
        print("scores.csv is empty.")
        return 1

    # Group by model
    by_model: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_model[rec["model"]].append(rec)

    rows: list[dict] = []
    for model in sorted(by_model):
        metrics = compute_metrics_for_model(by_model[model])
        row = {"model": model}
        for k, v in metrics.items():
            row[k] = round(v, 6) if v is not None else ""
        rows.append(row)
        print(f"{model}:")
        for k, v in metrics.items():
            print(f"  {k:4s} = {v:.6f}" if v is not None else f"  {k:4s} = N/A")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWritten -> {_relpath(out_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
