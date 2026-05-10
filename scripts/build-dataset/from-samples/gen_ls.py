"""
Generate LS (Local Shuffle) dataset from benchmark samples.

For every rule in ALL_RULES, loads the benchmark sample and converts each
entry to the standardized { premise_knowledge, expected_output } format
using shuffled real-world terms. Entries that cannot be shuffled (e.g. identical
swappable terms) are skipped.

The shuffle logic per rule is defined by the `shuffle_terms` key in RULE_CONFIGS.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared._base import (
    ALL_RULES,
    RULE_CONFIGS,
    load_benchmark_sample,
    make_dataset_entry,
    save_dataset,
)

DATASET_VARIANT = "ls"


def build_ls(rule: str) -> tuple[list[dict], str, str, str, list[str]]:
    entries, meta, filename = load_benchmark_sample(rule)
    cfg = RULE_CONFIGS[rule]
    fetch_uid = meta["fetch_uid"]
    fetched_at = meta.get("fetched_at", "")
    rules = meta["rules"]

    dataset: list[dict] = []
    skipped = 0
    for entry in entries:
        try:
            t = cfg["build_terms"](entry)
            t_shuffled = cfg["shuffle_terms"](t)
            if t_shuffled is None:
                skipped += 1
                continue
            dataset.append(
                make_dataset_entry(
                    premise_knowledge=cfg["build_premise"](t_shuffled),
                    expected_output=cfg["build_conclusion"](t_shuffled),
                )
            )
        except Exception as exc:
            print(f"  WARNING: skipping entry {entry}: {exc}")

    if skipped:
        print(f"  Skipped {skipped} entries (non-shuffleable terms)")

    return dataset, fetch_uid, fetched_at, filename, rules


def main() -> None:
    build_date = date.today().strftime("%Y%m%d")
    for rule in ALL_RULES:
        print(f"\n=== {rule} ===")
        try:
            dataset, fetch_uid, fetched_at, filename, rules = build_ls(rule)
            save_dataset(dataset, rule, DATASET_VARIANT, fetch_uid, fetched_at, filename, build_date=build_date, rules=rules)
        except FileNotFoundError as exc:
            print(f"  SKIP: {exc}")


if __name__ == "__main__":
    main()
