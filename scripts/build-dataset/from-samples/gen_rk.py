"""
Generate RK (Real-world Knowledge) dataset from benchmark samples.

By default, loads every benchmark sample and converts each
entry to the standardized { premise_knowledge, expected_output } format
using real DBpedia / Wikidata / schema.org term names.
"""

import os
import sys
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared._base import (
    RULE_CONFIGS,
    load_benchmark_sample,
    make_dataset_entry,
    parse_patterns_arg,
    save_dataset,
    wikidata_label_metadata,
)

DATASET_VARIANT = "rk"
WIKIDATA_LABEL_CONVERSION = "ascii_fold"


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


def build_rk(rule: str) -> tuple[list[dict], str, str, str, list[str], dict]:
    entries, meta, filename = load_benchmark_sample(rule)
    cfg = RULE_CONFIGS[rule]
    fetch_uid = meta["fetch_uid"]
    fetched_at = meta.get("fetched_at", "")
    rules = meta["rules"]
    extra_metadata = wikidata_label_metadata(entries, WIKIDATA_LABEL_CONVERSION)

    dataset: list[dict] = []
    for entry in entries:
        try:
            t = cfg["build_terms"](entry, ascii_fold=True)
            dataset.append(
                make_dataset_entry(
                    premise_knowledge=cfg["build_premise"](t),
                    expected_output=cfg["build_conclusion"](t),
                )
            )
        except Exception as exc:
            print(f"  WARNING: skipping entry {entry}: {exc}")

    return dataset, fetch_uid, fetched_at, filename, rules, extra_metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RK datasets from benchmark samples.")
    parser.add_argument("--patterns", default=None, help="Comma-separated pattern ids. Default: all patterns.")
    args = parser.parse_args()

    build_date = date.today().strftime("%Y%m%d")
    for rule in parse_patterns_arg(args.patterns):
        print(f"\n=== {rule} ===")
        try:
            dataset, fetch_uid, fetched_at, filename, rules, extra_metadata = build_rk(rule)
            save_dataset(
                dataset,
                rule,
                DATASET_VARIANT,
                fetch_uid,
                fetched_at,
                filename,
                build_date=build_date,
                rules=rules,
                extra_metadata=extra_metadata,
            )
        except FileNotFoundError as exc:
            print(f"  SKIP: {exc}")


if __name__ == "__main__":
    main()
