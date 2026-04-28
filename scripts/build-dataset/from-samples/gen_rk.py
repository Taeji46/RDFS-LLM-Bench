"""
Generate RK (Real-world Knowledge) dataset from benchmark samples.

For every rule in ALL_RULES, loads the benchmark sample and converts each
entry to the standardized { premise_knowledge, expected_output } format
using real DBpedia / Wikidata / LOV term names.
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

DATASET_TYPE = "rk"


def _infer_source(meta: dict) -> str:
    """Infer short source name from metadata. Falls back to endpoint URL."""
    if "source" in meta:
        return meta["source"]
    endpoints: list[str] = meta.get("endpoints", [])
    if not endpoints:
        return "unknown"
    ep = endpoints[0]
    if "wikidata" in ep:
        return "wdt"
    if "dbpedia" in ep:
        return "dbp"
    if "lov" in ep:
        return "lov"
    return "unknown"


def build_rk(rule: str) -> tuple[list[dict], str, str, str]:
    entries, meta, filename = load_benchmark_sample(rule)
    cfg = RULE_CONFIGS[rule]
    fetch_uid = meta["fetch_uid"]
    fetched_at = meta.get("fetched_at", "")

    dataset: list[dict] = []
    for entry in entries:
        try:
            t = cfg["build_terms"](entry)
            dataset.append(
                make_dataset_entry(
                    premise_knowledge=cfg["build_premise"](t),
                    expected_output=cfg["build_conclusion"](t),
                )
            )
        except Exception as exc:
            print(f"  WARNING: skipping entry {entry}: {exc}")

    return dataset, fetch_uid, fetched_at, filename


def main() -> None:
    build_date = date.today().strftime("%Y%m%d")
    for rule in ALL_RULES:
        print(f"\n=== {rule} ===")
        try:
            dataset, fetch_uid, fetched_at, filename = build_rk(rule)
            save_dataset(dataset, rule, DATASET_TYPE, fetch_uid, fetched_at, filename, build_date=build_date)
        except FileNotFoundError as exc:
            print(f"  SKIP: {exc}")


if __name__ == "__main__":
    main()
