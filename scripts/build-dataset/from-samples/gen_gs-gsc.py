"""
Generate GS (Global Shuffle) and GSC (Global Shuffle + Case conversion) datasets
from benchmark samples.

GS : all terms deranged together in one pool; original local names preserved.
GSC: same shuffled terms with name conversion applied:
       a, b  → to_instance_name  (PascalCase with underscores)
       i,j,k → to_property_name  (camelCase)
       x,y,z,w → to_class_name   (PascalCase)

Both datasets are generated in the same loop and saved separately.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared._base import (
    ALL_RULES,
    RULE_CONFIGS,
    _derange_list,
    gsc_convert,
    load_benchmark_sample,
    make_dataset_entry,
    save_dataset,
)


def build_gs_gsc(rule: str) -> tuple[list[dict], list[dict], str, str, str]:
    entries, meta, filename = load_benchmark_sample(rule)
    cfg = RULE_CONFIGS[rule]
    fetch_uid = meta["fetch_uid"]
    fetched_at = meta.get("fetched_at", "")

    gs_dataset: list[dict] = []
    gsc_dataset: list[dict] = []
    skipped = 0

    for entry in entries:
        try:
            t = cfg["build_terms"](entry)
            keys = list(t.keys())
            vals = [t[k] for k in keys]

            deranged = _derange_list(vals)
            if deranged is None:
                skipped += 1
                continue

            t_gs = dict(zip(keys, deranged))

            gs_dataset.append(
                make_dataset_entry(
                    premise_knowledge=cfg["build_premise"](t_gs),
                    expected_output=cfg["build_conclusion"](t_gs),
                )
            )

            t_gsc = gsc_convert(t_gs)
            gsc_dataset.append(
                make_dataset_entry(
                    premise_knowledge=cfg["build_premise"](t_gsc),
                    expected_output=cfg["build_conclusion"](t_gsc),
                )
            )

        except Exception as exc:
            print(f"  WARNING: skipping entry {entry}: {exc}")

    if skipped:
        print(f"  Skipped {skipped} entries (non-derangeable terms)")

    return gs_dataset, gsc_dataset, fetch_uid, fetched_at, filename


GS_SKIP_RULES = {"rdfs5", "rdfs11"}  # all terms same resource type → derangement meaningless


def main() -> None:
    build_date = date.today().strftime("%Y%m%d")
    for rule in ALL_RULES:
        if rule in GS_SKIP_RULES:
            print(f"\n=== {rule} === SKIP (all terms same resource type)")
            continue
        print(f"\n=== {rule} ===")
        try:
            gs_dataset, gsc_dataset, fetch_uid, fetched_at, filename = build_gs_gsc(rule)
            save_dataset(gs_dataset,  rule, "gs",  fetch_uid, fetched_at, filename, build_date=build_date)
            save_dataset(gsc_dataset, rule, "gsc", fetch_uid, fetched_at, filename, build_date=build_date)
        except FileNotFoundError as exc:
            print(f"  SKIP: {exc}")


if __name__ == "__main__":
    main()
