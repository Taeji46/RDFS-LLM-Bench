"""
Generate NS (Non-Semantic) dataset.

Each entry is built by assigning random 8-character alphanumeric strings
to all term slots of a rule regardless of term type (instance/property/class).
No distinctness constraints are applied.

Corresponds to legacy "NSD" (Non-Semantic Dataset).
"""

import os
import random
import string
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
)

# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 400

# ──────────────────────────────────────────────────────────────────
# Term variable lists per rule
# ──────────────────────────────────────────────────────────────────
_RULE_VARS: dict[str, list[str]] = {
    "rdfs2":      ["a", "b", "i", "x"],
    "rdfs3":      ["a", "b", "i", "x"],
    "rdfs5":      ["i", "j", "k"],
    "rdfs7":      ["a", "b", "i", "j"],
    "rdfs9":      ["a", "x", "y"],
    "rdfs11":     ["x", "y", "z"],
    "rdfs2_3":    ["a", "b", "i", "x", "y"],
    "rdfs2_7":    ["a", "b", "i", "j", "x"],
    "rdfs2_9":    ["a", "b", "i", "x", "y"],
    "rdfs3_7":    ["a", "b", "i", "j", "x"],
    "rdfs3_9":    ["a", "b", "i", "x", "y"],
    "rdfs5_7":    ["a", "b", "i", "j", "k"],
    "rdfs9_11":   ["a", "x", "y", "z"],
    "rdfs2_3_7":  ["a", "b", "i", "j", "x", "y"],
    "rdfs2_3_9":  ["a", "b", "i", "x", "y", "z", "w"],
    "rdfs2_5_7":  ["a", "b", "i", "j", "k", "x"],
    "rdfs2_9_11": ["a", "b", "i", "x", "y", "z"],
    "rdfs3_5_7":  ["a", "b", "i", "j", "k", "x"],
    "rdfs3_9_11": ["a", "b", "i", "x", "y", "z"],
}

_CHARS = string.ascii_letters + string.digits


def _random_token(length: int = 8) -> str:
    """Generate a random alphanumeric string (same as legacy NSD vocabulary)."""
    return "".join(random.choices(_CHARS, k=length))


# ──────────────────────────────────────────────────────────────────
# Per-rule dataset builder
# ──────────────────────────────────────────────────────────────────
def build_ns(rule: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    cfg = RULE_CONFIGS[rule]
    vars_ = _RULE_VARS[rule]
    dataset: list[dict] = []

    for _ in range(limit):
        t = {v: _random_token() for v in vars_}
        dataset.append(
            make_dataset_entry(
                premise_knowledge=cfg["build_premise"](t),
                expected_output=cfg["build_conclusion"](t),
            )
        )

    return dataset


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NS datasets.")
    parser.add_argument("--patterns", default=None, help="Comma-separated pattern ids. Default: all patterns.")
    args = parser.parse_args()

    build_date = date.today().strftime("%Y%m%d")

    for rule in parse_patterns_arg(args.patterns):
        print(f"\n=== {rule} ===")
        _, meta, _ = load_benchmark_sample(rule)
        dataset = build_ns(rule)
        save_dataset(
            dataset,
            rule,
            "ns",
            build_date=build_date,
            rules=meta["rules"],
        )


if __name__ == "__main__":
    main()
