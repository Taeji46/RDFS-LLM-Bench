"""Export aggregated scores to Excel workbooks.

Reads:
  data/llm-eval/reports/scores.csv

Writes one .xlsx per model:
  data/llm-eval/reports/scores__{model}.xlsx

Each workbook has one sheet per operation_type (e.g. NRP-full, ARP-full, ...).
Each sheet is a pivot table:
  rows    = rule_id  (sorted by n_rule, then rule_id)
  columns = dataset_type
  values  = accuracy
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[3]

DEFAULT_REPORT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "reports"

# Canonical display order for operation types
OPERATION_TYPE_ORDER = [
    "NRP-full", "NRP-name", "NRP-def",
    "ARP-full", "ARP-name", "ARP-def",
]

# Canonical display order for dataset types
DATASET_TYPE_ORDER = ["rk", "ls", "gs", "gsc", "rva", "ns", "nsc"]


def _relpath(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _rule_sort_key(rule_id: str) -> tuple:
    """Sort by n_rule first, then constituent rule numbers numerically.

    e.g. rdfs2 < rdfs3 < rdfs11, rdfs2_3 < rdfs2_7 < rdfs9_11
    """
    import re
    nums = [int(x) for x in re.findall(r'\d+', rule_id)]
    return (len(nums), nums)


def _load_scores(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_workbook(model: str, records: list[dict], report_root: Path, overwrite: bool, mode: str = "strict") -> bool:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl is required: pip install openpyxl")
        return False

    out_path = report_root / f"scores-{mode}__{model}.xlsx"
    if out_path.exists() and not overwrite:
        print(f"  SKIP (exists): {_relpath(out_path)}")
        return True

    # Group records by operation_type
    by_op: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_op[rec["operation_type"]].append(rec)

    wb = openpyxl.Workbook()
    default_ws = wb.active
    assert default_ws is not None
    wb.remove(default_ws)  # remove default sheet

    # Determine operation_type order
    op_types = [op for op in OPERATION_TYPE_ORDER if op in by_op]
    # Append any unexpected operation types at the end
    for op in sorted(by_op):
        if op not in op_types:
            op_types.append(op)

    ARP_OPS = {"ARP-full", "ARP-name", "ARP-def"}

    # Build list of sheets: (sheet_title, op_type, metric_col)
    sheets: list[tuple[str, str, str]] = []
    for op_type in op_types:
        sheets.append((op_type, op_type, "f1_triple"))
        if op_type in ARP_OPS:
            sheets.append((f"{op_type}-rule", op_type, "f1_rule"))

    for sheet_title, op_type, metric_col in sheets:
        op_records = by_op[op_type]

        # Collect unique rule_ids and dataset_types
        rule_ids = sorted({r["rule_id"] for r in op_records}, key=_rule_sort_key)
        ds_types = [d for d in DATASET_TYPE_ORDER if any(r["dataset_type"] == d for r in op_records)]
        for d in sorted({r["dataset_type"] for r in op_records}):
            if d not in ds_types:
                ds_types.append(d)

        # Build lookup: (rule_id, dataset_type) -> metric value
        lookup: dict[tuple, float] = {}
        for rec in op_records:
            raw = rec.get(metric_col, "")
            if raw == "" or raw is None:
                continue
            try:
                lookup[(rec["rule_id"], rec["dataset_type"])] = float(raw)
            except ValueError:
                pass

        is_rule_sheet = metric_col == "f1_rule"
        header_color = "70AD47" if is_rule_sheet else "4472C4"  # green for rule sheets
        row_color    = "E2EFDA" if is_rule_sheet else "D9E1F2"

        ws = wb.create_sheet(title=sheet_title)

        header_fill = PatternFill("solid", fgColor=header_color)
        header_font = Font(bold=True, color="FFFFFF")
        center = Alignment(horizontal="center")

        ws.cell(row=1, column=1, value="rule_id").font = Font(bold=True)
        ws.cell(row=1, column=1).fill = PatternFill("solid", fgColor="D9D9D9")
        for col_idx, ds in enumerate(ds_types, start=2):
            cell = ws.cell(row=1, column=col_idx, value=ds)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

        for row_idx, rule_id in enumerate(rule_ids, start=2):
            cell = ws.cell(row=row_idx, column=1, value=rule_id)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor=row_color)

            for col_idx, ds in enumerate(ds_types, start=2):
                val = lookup.get((rule_id, ds))
                cell = ws.cell(row=row_idx, column=col_idx)
                if val is not None:
                    cell.value = round(val, 6)
                    cell.number_format = "0.000000"
                    cell.alignment = center
                else:
                    cell.value = "/"
                    cell.alignment = center

        ws.column_dimensions["A"].width = 16
        for col_idx in range(2, len(ds_types) + 2):
            ws.column_dimensions[get_column_letter(col_idx)].width = 12

    report_root.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"  -> {_relpath(out_path)}  ({len(sheets)} sheets)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export scores.csv to per-model Excel workbooks."
    )
    parser.add_argument("--mode", type=str, default="strict",
                        choices=["strict", "flex"],
                        help="Evaluation mode (default: strict)")
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--models", type=str, default="",
                        help="Comma-separated model names to filter (default: all)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    mode = args.mode
    report_root = args.report_root.resolve() / mode
    csv_path = report_root / f"scores-{mode}.csv"

    if not csv_path.exists():
        print(f"scores.csv not found: {_relpath(csv_path)}")
        print("Run aggregate_scores.py first.")
        return 1

    records = _load_scores(csv_path)
    if not records:
        print("scores.csv is empty.")
        return 1

    model_filter = {s.strip() for s in args.models.split(",") if s.strip()}

    # Group by model
    by_model: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_model[rec["model"]].append(rec)

    models = sorted(m for m in by_model if not model_filter or m in model_filter)
    if not models:
        print("No models matched the filter.")
        return 1

    print(f"Exporting {len(models)} model(s) ...")
    for model in models:
        _write_workbook(model, by_model[model], report_root, args.overwrite, mode)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
