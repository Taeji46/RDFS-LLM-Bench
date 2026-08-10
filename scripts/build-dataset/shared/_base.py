"""
Shared utilities and RULE_CONFIGS for build-dataset scripts.

Provides:
  - Term extraction helpers: get_term(), to_property_name(), to_class_name(), to_instance_name()
  - RULE_CONFIGS: per-rule build_terms / build_premise / build_conclusion lambdas
  - Rule group lists: RULES_1, RULES_2, RULES_3, ALL_RULES
  - I/O helpers: find_benchmark_sample(), load_benchmark_sample(), save_dataset()
"""

import json
import os
import re
import unicodedata
from datetime import date as _date

# ──────────────────────────────────────────────────────────────────
# Project paths
# ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOD_SAMPLES_DIR = os.path.join(PROJECT_ROOT, "data", "lod-samples")
DATASETS_DIR = os.path.join(PROJECT_ROOT, "data", "datasets")


# ──────────────────────────────────────────────────────────────────
# General helpers
# ──────────────────────────────────────────────────────────────────
def all_distinct(*vals) -> bool:
    """Return True if all values are distinct (no duplicates)."""
    return len(set(vals)) == len(vals)


# ──────────────────────────────────────────────────────────────────
# Term extraction helpers
# ──────────────────────────────────────────────────────────────────
def get_term(uri: str) -> str:
    """Extract local name from a URI.
    e.g. 'http://dbpedia.org/ontology/Person' → 'Person'
    """
    if not uri:
        raise ValueError("URI cannot be empty.")
    return uri.split("/")[-1]


def _ascii_fold(s: str) -> str:
    """Transliterate accented characters to ASCII via NFKD decomposition.
    e.g. 'café' → 'cafe', 'Cristián' → 'Cristian', 'Köln' → 'Koln'.
    Characters that don't decompose (e.g. 'Ø', 'æ') are left unchanged
    and will still be dropped by the regex in _split_words.
    """
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _split_words(s: str, *, ascii_fold: bool = True) -> list[str]:
    if ascii_fold:
        s = _ascii_fold(s)
    parts = re.split(r"[ _]+", s)
    words: list[str] = []
    for part in parts:
        words.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+|[\(\)]", part))
    return [w for w in words if w]


def to_property_name(s: str, *, ascii_fold: bool = True) -> str:
    """Convert string to camelCase property name.
    e.g. 'crosses river2 (bridge)' → 'crossesRiver2Bridge'
    """
    words = _split_words(s, ascii_fold=ascii_fold)
    filtered = [w for w in words if w not in ("(", ")")]
    if not filtered:
        return ""
    first = filtered[0].lower() if not filtered[0].isdigit() else filtered[0]
    rest = [w.capitalize() if not w.isdigit() else w for w in filtered[1:]]
    return first + "".join(rest)


def to_class_name(s: str, *, ascii_fold: bool = True) -> str:
    """Convert string to PascalCase class name.
    e.g. 'river clyde2 (bridge)' → 'RiverClyde2Bridge'
    """
    words = _split_words(s, ascii_fold=ascii_fold)
    return "".join(
        w.capitalize() if not w.isdigit() and w not in ("(", ")") else w
        for w in words
        if w not in ("(", ")")
    )


def to_instance_name(s: str, *, ascii_fold: bool = True) -> str:
    """Convert string to underscore-separated PascalCase instance name.
    e.g. 'river clyde2 (bridge)' → 'River_Clyde2_(Bridge)'
    """
    words = _split_words(s, ascii_fold=ascii_fold)
    return "_".join(
        w.capitalize() if not w.isdigit() and w not in ("(", ")") else w
        for w in words
    )


# ──────────────────────────────────────────────────────────────────
# GSC name conversion
# ──────────────────────────────────────────────────────────────────
_GSC_TERM_TYPE: dict[str, str] = {
    "a": "instance", "b": "instance",
    "i": "property", "j": "property", "k": "property",
    "x": "class",    "y": "class",    "z": "class",    "w": "class",
}
_GSC_TERM_FN = {
    "instance": to_instance_name,
    "property": to_property_name,
    "class":    to_class_name,
}

def gsc_convert(t: dict, *, ascii_fold: bool = True) -> dict:
    """Apply GSC name formatting to a terms dict (a/b→instance, i/j/k→property, x/y/z/w→class)."""
    return {k: _GSC_TERM_FN[_GSC_TERM_TYPE[k]](v, ascii_fold=ascii_fold) for k, v in t.items()}


# ──────────────────────────────────────────────────────────────────
# Convenience shorthands used inside RULE_CONFIGS lambdas
# ──────────────────────────────────────────────────────────────────
def _t(entry: dict, field: str) -> str:
    """get_term() on a URI field."""
    return get_term(entry[field])


def _p(entry: dict, field: str, *, ascii_fold: bool = True) -> str:
    """to_property_name() on a label field."""
    return to_property_name(entry[field], ascii_fold=ascii_fold)


_WDT_PREFIX = "http://www.wikidata.org/entity/"


def _pn(entry: dict, field: str, *, ascii_fold: bool = True) -> str:
    """Extract a camelCase property name, choosing the source by URI type.

    - Wikidata URI (opaque P-ID): use entry[f"{field}_label"] → camelCase.
    - Other URI (schema.org / DBpedia ontology): use the URI local name as-is.
    """
    uri = entry.get(field, "")
    if uri.startswith(_WDT_PREFIX):
        return to_property_name(entry[f"{field}_label"], ascii_fold=ascii_fold)
    return get_term(uri)


# ──────────────────────────────────────────────────────────────────
# Shuffle helpers (used in RULE_CONFIGS shuffle_terms)
# ──────────────────────────────────────────────────────────────────
def _derange_list(vals: list[str]) -> list[str] | None:
    """Return a deterministic derangement of vals (no element stays in place).
    Tries rotations first, then all permutations. Returns None if impossible.
    """
    from itertools import permutations as _perms

    n = len(vals)
    if n <= 1:
        return None
    for shift in range(1, n):
        candidate = vals[shift:] + vals[:shift]
        if all(candidate[i] != vals[i] for i in range(n)):
            return candidate
    for perm in _perms(vals):
        if all(perm[i] != vals[i] for i in range(n)):
            return list(perm)
    return None


def _sw(t: dict, k1: str, k2: str) -> dict | None:
    """Swap values of two keys in a terms dict. Returns None if values are equal."""
    if t[k1] == t[k2]:
        return None
    return {**t, k1: t[k2], k2: t[k1]}


def _dr(t: dict, *keys: str) -> dict | None:
    """Derange values of given keys in a terms dict. Returns None if impossible."""
    vals = [t[k] for k in keys]
    deranged = _derange_list(vals)
    if deranged is None:
        return None
    return {**t, **dict(zip(keys, deranged))}


def _chain(*fns):
    """Chain shuffle operations. Each fn: dict -> dict | None. Short-circuits on None."""
    def apply(t: dict) -> dict | None:
        result = t
        for fn in fns:
            result = fn(result)
            if result is None:
                return None
        return result
    return apply


# ──────────────────────────────────────────────────────────────────
# Rule groups
# ──────────────────────────────────────────────────────────────────
RULES_1: list[str] = ["rdfs2", "rdfs3", "rdfs5", "rdfs7", "rdfs9", "rdfs11"]
RULES_2: list[str] = ["rdfs2_3", "rdfs2_7", "rdfs2_9", "rdfs3_7", "rdfs3_9", "rdfs5_7", "rdfs9_11"]
RULES_3: list[str] = ["rdfs2_3_7", "rdfs2_3_9", "rdfs2_5_7", "rdfs2_9_11", "rdfs3_5_7", "rdfs3_9_11"]
ALL_RULES: list[str] = RULES_1 + RULES_2 + RULES_3


# ──────────────────────────────────────────────────────────────────
# RULE_CONFIGS
#
# Each entry contains:
#   rule_str        : if-then string (matches legacy NSD format exactly)
#   build_terms     : fn(entry: dict) → dict[str, str]  — local-name strings
#   build_premise   : fn(terms: dict) → str             — premise_knowledge value
#   build_conclusion: fn(terms: dict) → str             — expected_output value
#
# DBpedia entries  : all fields are full URIs  → use _t(entry, field)
# Wikidata entries : i_dbp is a URI, j_label/k_label are plain labels
#                    → use _t(entry, "i_dbp") and _p(entry, "j_label") / _p(entry, "k_label")
# ──────────────────────────────────────────────────────────────────
RULE_CONFIGS: dict[str, dict] = {

    # ── 1-rule ──────────────────────────────────────────────────────
    "rdfs2": {
        "rule_str": "if <i, rdfs:domain, X> and <a, i, b> then <a, rdf:type, X>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: f"<{t['a']}, rdf:type, {t['x']}>",
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b')),
    },

    "rdfs3": {
        "rule_str": "if <i, rdfs:range, X> and <a, i, b> then <b, rdf:type, X>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:range, {t['x']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: f"<{t['b']}, rdf:type, {t['x']}>",
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b')),
    },

    "rdfs5": {
        "rule_str": "if <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> then <i, rdfs:subPropertyOf, k>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "i": _pn(e, "i", ascii_fold=ascii_fold), "j": _pn(e, "j", ascii_fold=ascii_fold), "k": _pn(e, "k", ascii_fold=ascii_fold),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:subPropertyOf, {t['j']}>, <{t['j']}, rdfs:subPropertyOf, {t['k']}>"
        ),
        "build_conclusion": lambda t: f"<{t['i']}, rdfs:subPropertyOf, {t['k']}>",
        "shuffle_terms": _chain(lambda t: _dr(t, 'i', 'j', 'k')),
    },

    "rdfs7": {
        # Wikidata: i_dbp is URI, j_label is plain label
        "rule_str": "if <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, j, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:subPropertyOf, {t['j']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: f"<{t['a']}, {t['j']}, {t['b']}>",
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'i', 'j')),
    },

    "rdfs9": {
        "rule_str": "if <X, rdfs:subClassOf, Y> and <a, rdf:type, X> then <a, rdf:type, Y>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"),
            "x": _t(e, "x"), "y": _t(e, "y"),
        },
        "build_premise": lambda t: (
            f"<{t['x']}, rdfs:subClassOf, {t['y']}>, <{t['a']}, rdf:type, {t['x']}>"
        ),
        "build_conclusion": lambda t: f"<{t['a']}, rdf:type, {t['y']}>",
        "shuffle_terms": _chain(lambda t: _sw(t, 'x', 'y')),
    },

    "rdfs11": {
        "rule_str": "if <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> then <X, rdfs:subClassOf, Z>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "x": _t(e, "x"), "y": _t(e, "y"), "z": _t(e, "z"),
        },
        "build_premise": lambda t: (
            f"<{t['x']}, rdfs:subClassOf, {t['y']}>, <{t['y']}, rdfs:subClassOf, {t['z']}>"
        ),
        "build_conclusion": lambda t: f"<{t['x']}, rdfs:subClassOf, {t['z']}>",
        "shuffle_terms": _chain(lambda t: _dr(t, 'x', 'y', 'z')),
    },

    # ── 2-rule ──────────────────────────────────────────────────────
    "rdfs2_3": {
        "rule_str": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <a, i, b> then <a, rdf:type, X> and <b, rdf:type, Y>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "x": _t(e, "x"), "y": _t(e, "y"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['i']}, rdfs:range, {t['y']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['b']}, rdf:type, {t['y']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'x', 'y')),
    },

    "rdfs2_7": {
        "rule_str": "if <i, rdfs:domain, X> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, rdf:type, X> and <a, j, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "j": _t(e, "j"), "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['j']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['a']}, {t['j']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'i', 'j')),
    },

    "rdfs2_9": {
        "rule_str": "if <i, rdfs:domain, X> and <X, rdfs:subClassOf, Y> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Y>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "x": _t(e, "x"), "y": _t(e, "y"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['x']}, rdfs:subClassOf, {t['y']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['a']}, rdf:type, {t['y']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'x', 'y')),
    },

    "rdfs3_7": {
        # Wikidata: i_dbp is URI, j_label is plain label
        "rule_str": "if <i, rdfs:range, X> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <b, rdf:type, X> and <a, j, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold), "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:range, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['j']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['b']}, rdf:type, {t['x']}>, <{t['a']}, {t['j']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'i', 'j')),
    },

    "rdfs3_9": {
        "rule_str": "if <i, rdfs:range, X> and <X, rdfs:subClassOf, Y> and <a, i, b> then <b, rdf:type, X> and <b, rdf:type, Y>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"), "x": _t(e, "x"), "y": _t(e, "y"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:range, {t['x']}>, <{t['x']}, rdfs:subClassOf, {t['y']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['b']}, rdf:type, {t['x']}>, <{t['b']}, rdf:type, {t['y']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'x', 'y')),
    },

    "rdfs5_7": {
        # Wikidata: i_dbp is URI, j_label/k_label are plain labels
        "rule_str": "if <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold), "k": _p(e, "k_label", ascii_fold=ascii_fold),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:subPropertyOf, {t['j']}>, <{t['j']}, rdfs:subPropertyOf, {t['k']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['i']}, rdfs:subPropertyOf, {t['k']}>, "
            f"<{t['a']}, {t['j']}, {t['b']}>, <{t['a']}, {t['k']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _dr(t, 'i', 'j', 'k')),
    },

    "rdfs9_11": {
        "rule_str": "if <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, rdf:type, X> then <a, rdf:type, Y> and <a, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"),
            "x": _t(e, "x"), "y": _t(e, "y"), "z": _t(e, "z"),
        },
        "build_premise": lambda t: (
            f"<{t['x']}, rdfs:subClassOf, {t['y']}>, <{t['y']}, rdfs:subClassOf, {t['z']}>, "
            f"<{t['a']}, rdf:type, {t['x']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['y']}>, <{t['a']}, rdf:type, {t['z']}>, "
            f"<{t['x']}, rdfs:subClassOf, {t['z']}>"
        ),
        "shuffle_terms": _chain(lambda t: _dr(t, 'x', 'y', 'z')),
    },

    # ── 3-rule ──────────────────────────────────────────────────────
    "rdfs2_3_7": {
        # Wikidata: i_dbp is URI, j_label is plain label
        "rule_str": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, rdf:type, X> and <b, rdf:type, Y> and <a, j, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold),
            "x": _t(e, "x"), "y": _t(e, "y"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['i']}, rdfs:range, {t['y']}>, "
            f"<{t['i']}, rdfs:subPropertyOf, {t['j']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['b']}, rdf:type, {t['y']}>, "
            f"<{t['a']}, {t['j']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _sw(t, 'i', 'j'), lambda t: _sw(t, 'x', 'y')),
    },

    "rdfs2_3_9": {
        "rule_str": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <X, rdfs:subClassOf, Z> and <Y, rdfs:subClassOf, W> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Z> and <b, rdf:type, Y> and <b, rdf:type, W>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"),
            "x": _t(e, "x"), "y": _t(e, "y"),
            "z": _t(e, "z"), "w": _t(e, "w"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['i']}, rdfs:range, {t['y']}>, "
            f"<{t['x']}, rdfs:subClassOf, {t['z']}>, <{t['y']}, rdfs:subClassOf, {t['w']}>, "
            f"<{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['a']}, rdf:type, {t['z']}>, "
            f"<{t['b']}, rdf:type, {t['y']}>, <{t['b']}, rdf:type, {t['w']}>"
        ),
        # Legacy: x,z = swap([y,w]); y,w = swap([x,z])  (using original x,z values)
        # skip when a==b OR y==w (range class==superclass) OR x==z (domain class==superclass)
        # result: x=w_orig, z=y_orig, y=z_orig, w=x_orig
        "shuffle_terms": lambda t: (
            None if t['a'] == t['b'] or t['y'] == t['w'] or t['x'] == t['z']
            else {**t, 'a': t['b'], 'b': t['a'],
                  'x': t['w'], 'z': t['y'], 'y': t['z'], 'w': t['x']}
        ),
    },

    "rdfs2_5_7": {
        # Wikidata: i_dbp is URI, j_label/k_label are plain labels
        "rule_str": "if <i, rdfs:domain, X> and <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <a, rdf:type, X> and <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold), "k": _p(e, "k_label", ascii_fold=ascii_fold),
            "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['j']}>, "
            f"<{t['j']}, rdfs:subPropertyOf, {t['k']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['k']}>, "
            f"<{t['a']}, {t['j']}, {t['b']}>, <{t['a']}, {t['k']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _dr(t, 'i', 'j', 'k')),
    },

    "rdfs2_9_11": {
        "rule_str": "if <i, rdfs:domain, X> and <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Y> and <a, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"),
            "x": _t(e, "x"), "y": _t(e, "y"), "z": _t(e, "z"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:domain, {t['x']}>, <{t['x']}, rdfs:subClassOf, {t['y']}>, "
            f"<{t['y']}, rdfs:subClassOf, {t['z']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['a']}, rdf:type, {t['x']}>, <{t['a']}, rdf:type, {t['y']}>, "
            f"<{t['a']}, rdf:type, {t['z']}>, <{t['x']}, rdfs:subClassOf, {t['z']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _dr(t, 'x', 'y', 'z')),
    },

    "rdfs3_5_7": {
        # Wikidata: i_dbp is URI, j_label/k_label are plain labels
        "rule_str": "if <i, rdfs:range, X> and <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <b, rdf:type, X> and <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i_dbp"), "j": _p(e, "j_label", ascii_fold=ascii_fold), "k": _p(e, "k_label", ascii_fold=ascii_fold),
            "x": _t(e, "x"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:range, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['j']}>, "
            f"<{t['j']}, rdfs:subPropertyOf, {t['k']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['b']}, rdf:type, {t['x']}>, <{t['i']}, rdfs:subPropertyOf, {t['k']}>, "
            f"<{t['a']}, {t['j']}, {t['b']}>, <{t['a']}, {t['k']}, {t['b']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _dr(t, 'i', 'j', 'k')),
    },

    "rdfs3_9_11": {
        "rule_str": "if <i, rdfs:range, X> and <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, i, b> then <b, rdf:type, X> and <b, rdf:type, Y> and <b, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
        "build_terms": lambda e, *, ascii_fold=True: {
            "a": _t(e, "a"), "b": _t(e, "b"),
            "i": _t(e, "i"),
            "x": _t(e, "x"), "y": _t(e, "y"), "z": _t(e, "z"),
        },
        "build_premise": lambda t: (
            f"<{t['i']}, rdfs:range, {t['x']}>, <{t['x']}, rdfs:subClassOf, {t['y']}>, "
            f"<{t['y']}, rdfs:subClassOf, {t['z']}>, <{t['a']}, {t['i']}, {t['b']}>"
        ),
        "build_conclusion": lambda t: (
            f"<{t['b']}, rdf:type, {t['x']}>, <{t['b']}, rdf:type, {t['y']}>, "
            f"<{t['b']}, rdf:type, {t['z']}>, <{t['x']}, rdfs:subClassOf, {t['z']}>"
        ),
        "shuffle_terms": _chain(lambda t: _sw(t, 'a', 'b'), lambda t: _dr(t, 'x', 'y', 'z')),
    },
}


def parse_patterns_arg(patterns: str | None) -> list[str]:
    """Parse a comma-separated --patterns value, defaulting to ALL_RULES."""
    if patterns is None or not patterns.strip() or patterns.strip() in {"all", "*"}:
        return ALL_RULES

    requested: list[str] = []
    seen: set[str] = set()
    for raw in patterns.split(","):
        rule = raw.strip()
        if not rule:
            continue
        if rule not in RULE_CONFIGS:
            raise ValueError(f"Unknown pattern '{rule}'. Available patterns: {', '.join(ALL_RULES)}")
        if rule not in seen:
            requested.append(rule)
            seen.add(rule)

    if not requested:
        raise ValueError("--patterns did not contain any valid pattern ids")
    return requested


# ──────────────────────────────────────────────────────────────────
# I/O helpers
# ──────────────────────────────────────────────────────────────────
def _rule_to_nrule_dir(rule: str) -> str:
    if rule in RULES_1:
        return "1-rule"
    if rule in RULES_2:
        return "2-rule"
    if rule in RULES_3:
        return "3-rule"
    raise ValueError(f"Unknown rule: {rule}")


def make_dataset_entry(premise_knowledge: str, expected_output: str) -> dict:
    """Build one standardized dataset entry."""
    return {
        "premise_knowledge": premise_knowledge,
        "expected_output": expected_output,
    }


def wikidata_label_metadata(entries: list[dict], conversion: str) -> dict:
    """Return metadata for datasets that render Wikidata property labels.

    This is distinct from GSC case conversion. It documents only how Wikidata
    label fields are tokenized when converted to local property names.
    """
    has_label = any(
        any(key.endswith("_label") for key in entry)
        for entry in entries
    )
    return {"wikidata_label_conversion": conversion} if has_label else {}


def _load_lod_sample_config() -> dict[str, str]:
    config_path = os.path.join(PROJECT_ROOT, "scripts", "build-dataset", "lod-sample-config.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def find_benchmark_sample(rule: str) -> str:
    """Find the lod-sample file for a given rule using lod-sample-config.json. Returns the file path."""
    config = _load_lod_sample_config()
    if rule not in config:
        raise KeyError(f"Rule '{rule}' not found in lod-sample-config.json")
    filename = config[rule]
    subdir = _rule_to_nrule_dir(rule)
    path = os.path.join(LOD_SAMPLES_DIR, subdir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"lod-sample file not found: {path}")
    return path


def load_benchmark_sample(rule: str) -> tuple[list[dict], dict, str]:
    """Load benchmark sample for a rule. Returns (entries, metadata, filename)."""
    path = find_benchmark_sample(rule)
    print(f"Loading: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["entries"], data["metadata"], os.path.basename(path)


def save_dataset(
    entries: list[dict],
    rule: str,
    dataset_variant: str,
    fetch_uid: str | None = None,
    fetched_at: str | None = None,
    source_filename: str | None = None,
    output_dir: str | None = None,
    build_date: str | None = None,
    *,
    rules: list[str],
    extra_metadata: dict | None = None,
) -> str:
    """Save a dataset to JSON with metadata wrapper. Returns output path.

    LOD-sourced datasets (rk, ls, gs, gsc, rva):
      Filename: dataset__{type}__{rule}__n{count}__{fetch_uid}__b-{build_uid}.json
    Standalone datasets (ns, nsc):
      Filename: dataset__{type}__{rule}__n{count}__b-{build_uid}.json

    fetch_uid:       source sample UID (e.g. "f-ffef792c", "v-a1b2c3d4"); omit for standalone
    fetched_at:      fetch date from source metadata; omit for standalone
    source_filename: basename of the source sample file; omit for standalone
    build_uid:       generated at build time (e.g. "b-3a9c2b1d")
    """
    import uuid
    if build_date is None:
        build_date = _date.today().strftime("%Y%m%d")
    if output_dir is None:
        output_dir = os.path.join(DATASETS_DIR, dataset_variant, _rule_to_nrule_dir(rule))

    build_uid = "b-" + uuid.uuid4().hex[:8]

    metadata: dict = {
        "pattern_id": rule,
        "rules": rules,
        "dataset_variant": dataset_variant,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    if fetch_uid is not None:
        metadata["fetch_uid"] = fetch_uid
    if fetched_at is not None:
        metadata["fetched_at"] = fetched_at
    if source_filename is not None:
        metadata["source_filename"] = source_filename
    metadata["build_uid"] = build_uid
    metadata["built_at"] = build_date
    metadata["count"] = len(entries)

    output = {"metadata": metadata, "entries": entries}

    os.makedirs(output_dir, exist_ok=True)
    if fetch_uid is not None:
        filename = f"dataset__{dataset_variant}__{rule}__n{len(entries)}__{fetch_uid}__{build_uid}.json"
    else:
        filename = f"dataset__{dataset_variant}__{rule}__n{len(entries)}__{build_uid}.json"
    output_path = os.path.join(output_dir, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"Saved {len(entries)} entries to {output_path}")
    return output_path
