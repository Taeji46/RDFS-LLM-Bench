"""
Generate NSC (Non-Semantic with Case convention) dataset.

Each entry is built by assigning random strings to term slots
with type-appropriate naming conventions:
  - instance slots (a, b): PascalCase_With_Underscores  e.g. Iyotw_Jbsg
  - property slots (i, j, k): camelCase                 e.g. shpoAvtxn
  - class slots (x, y, z, w): PascalCase                e.g. UvpkElss

No distinctness constraints are applied.

Corresponds to legacy "NSC" (Non-Semantic with Case) dataset.
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
    _GSC_TERM_TYPE,
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


# ──────────────────────────────────────────────────────────────────
# Type-specific random token generators (mirrors legacy NSC vocabulary)
# ──────────────────────────────────────────────────────────────────
def _nsc_class() -> str:
    """PascalCase random string. e.g. 'SportResult', 'Uvpk'"""
    num_words = random.randint(1, 3)
    words = []
    for _ in range(num_words):
        length = random.randint(3, 6)
        words.append(random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=length - 1)))
    return "".join(words)


def _nsc_property() -> str:
    """camelCase random string. e.g. 'shpoAvtxn', 'ohymfmJwxr'"""
    num_words = random.randint(1, 3)
    words = []
    for idx in range(num_words):
        length = random.randint(3, 6)
        if idx == 0:
            words.append(random.choice(string.ascii_lowercase) + "".join(random.choices(string.ascii_lowercase, k=length - 1)))
        else:
            words.append(random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=length - 1)))
    return "".join(words)


def _nsc_instance() -> str:
    """PascalCase_With_Underscores random string. e.g. 'Iyotw_Jbsg_Crl'"""
    num_words = random.randint(1, 3)
    words = []
    for _ in range(num_words):
        length = random.randint(3, 6)
        words.append(random.choice(string.ascii_uppercase) + "".join(random.choices(string.ascii_lowercase, k=length - 1)))
    return "_".join(words)


_NSC_GEN = {
    "instance": _nsc_instance,
    "property": _nsc_property,
    "class":    _nsc_class,
}


def _nsc_token(var: str) -> str:
    return _NSC_GEN[_GSC_TERM_TYPE[var]]()


# ──────────────────────────────────────────────────────────────────
# Per-rule dataset builder
# ──────────────────────────────────────────────────────────────────
def build_nsc(rule: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    cfg = RULE_CONFIGS[rule]
    vars_ = _RULE_VARS[rule]
    dataset: list[dict] = []

    for _ in range(limit):
        t = {v: _nsc_token(v) for v in vars_}
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
    parser = argparse.ArgumentParser(description="Generate NSC datasets.")
    parser.add_argument("--patterns", default=None, help="Comma-separated pattern ids. Default: all patterns.")
    args = parser.parse_args()

    build_date = date.today().strftime("%Y%m%d")

    for rule in parse_patterns_arg(args.patterns):
        print(f"\n=== {rule} ===")
        _, meta, _ = load_benchmark_sample(rule)
        dataset = build_nsc(rule)
        save_dataset(
            dataset,
            rule,
            "nsc",
            build_date=build_date,
            rules=meta["rules"],
        )


if __name__ == "__main__":
    main()
