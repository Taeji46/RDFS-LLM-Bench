"""Scaling analysis: how f1_triple changes across 1-rule / 2-rule / 3-rule.

Filters to rule_info == "full" only.
Averages f1_triple per (dataset_type, model, operation_family, n_rule)
across all rule_ids.

Valid (operation_family, n_rule) combinations:
  NRP: 1, 2, 3
  ARP: 1, 2, 3

One sheet per dataset type (rk / ls / gs / gsc / ns / nsc / rva).
Each sheet: rows = (operation_family, n_rule), columns = models.

Reads:  data/llm-eval/reports/{mode}/scores-{mode}.csv
Writes: data/llm-eval/reports/{mode}/scaling_analysis-{mode}.xlsx
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[3]
DEFAULT_REPORT_ROOT = PROJECT_ROOT / "data" / "llm-eval" / "reports"

FAMILIES = ["NRP", "ARP"]
VALID_COMBOS = {
    "NRP": [1, 2, 3],
    "ARP": [1, 2, 3],
}
DATASET_TYPES = ["rk", "ls", "gs", "gsc", "ns", "nsc", "rva"]


def _relpath(p: Path) -> str:
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(p)


def _float(v: str) -> float | None:
    try:
        return float(v) if v != "" else None
    except ValueError:
        return None


def load_scores(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def compute(records: list[dict]) -> dict[str, dict[str, dict[tuple[str, int], float | None]]]:
    """Returns {dataset_type: {model: {(family, n_rule): mean_f1}}}."""
    buckets: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)

    for rec in records:
        if rec.get("rule_info") != "full":
            continue
        f1 = _float(rec.get("f1_triple", ""))
        if f1 is None:
            continue
        model = rec["model"]
        ds = rec["dataset_type"]
        family = rec["operation_family"]
        n_rule = int(rec["n_rule"])
        if family not in FAMILIES:
            continue
        if n_rule not in VALID_COMBOS.get(family, []):
            continue
        buckets[(ds, model, family, n_rule)].append(f1)

    models = sorted({k[1] for k in buckets})
    result: dict[str, dict[str, dict[tuple[str, int], float | None]]] = {}
    for ds in DATASET_TYPES:
        result[ds] = {}
        for model in models:
            result[ds][model] = {}
            for family, n_rules in VALID_COMBOS.items():
                for n_rule in n_rules:
                    vals = buckets.get((ds, model, family, n_rule), [])
                    result[ds][model][(family, n_rule)] = mean(vals) if vals else None
    return result


def _write_sheet(wb: openpyxl.Workbook, title: str, ds_data: dict[str, dict[tuple[str, int], float | None]], first: bool) -> None:
    if first:
        ws = wb.active
        assert ws is not None
        ws.title = title
    else:
        ws = wb.create_sheet(title=title)

    hdr_fill = PatternFill("solid", fgColor="4472C4")
    hdr_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center")
    right = Alignment(horizontal="right")

    models = sorted(ds_data.keys())

    ws.cell(row=1, column=1, value="operation_family").font = hdr_font
    ws.cell(row=1, column=1).fill = hdr_fill
    ws.cell(row=1, column=1).alignment = center
    ws.cell(row=1, column=2, value="n_rule").font = hdr_font
    ws.cell(row=1, column=2).fill = hdr_fill
    ws.cell(row=1, column=2).alignment = center
    for col, model in enumerate(models, 3):
        c = ws.cell(row=1, column=col, value=model)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = center

    row = 2
    for family in FAMILIES:
        for n_rule in VALID_COMBOS[family]:
            ws.cell(row=row, column=1, value=family).font = Font(bold=True)
            ws.cell(row=row, column=2, value=n_rule).font = Font(bold=True)
            for col, model in enumerate(models, 3):
                val = ds_data[model].get((family, n_rule))
                c = ws.cell(row=row, column=col, value=round(val, 4) if val is not None else "")
                c.alignment = right
                if val is not None:
                    c.number_format = "0.0000"
            row += 1

    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 10
    for col in range(3, len(models) + 3):
        ws.column_dimensions[get_column_letter(col)].width = 26
    ws.freeze_panes = "C2"


def write_excel(data: dict[str, dict[str, dict[tuple[str, int], float | None]]], out_path: Path) -> None:
    wb = openpyxl.Workbook()
    for i, ds in enumerate(DATASET_TYPES):
        _write_sheet(wb, ds, data[ds], first=(i == 0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"Written -> {_relpath(out_path)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="strict", choices=["strict", "flex"])
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    csv_path = args.report_root.resolve() / args.mode / f"scores-{args.mode}.csv"
    out_path = args.report_root.resolve() / args.mode / f"scaling_analysis-{args.mode}.xlsx"

    if not csv_path.exists():
        print(f"Not found: {_relpath(csv_path)}")
        return 1
    if out_path.exists() and not args.overwrite:
        print(f"Output already exists (use --overwrite): {_relpath(out_path)}")
        return 1

    records = load_scores(csv_path)
    data = compute(records)

    for ds in DATASET_TYPES:
        print(f"[{ds}]")
        for family in FAMILIES:
            for n_rule in VALID_COMBOS[family]:
                vals = {m: data[ds][m].get((family, n_rule)) for m in sorted(data[ds])}
                row_str = "  ".join(f"{m}={v:.4f}" if v is not None else f"{m}=N/A" for m, v in vals.items())
                print(f"  {family} {n_rule}-rule: {row_str}")

    write_excel(data, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
