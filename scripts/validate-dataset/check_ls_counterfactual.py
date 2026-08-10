"""Audit whether LS (Local Shuffle) novel premise triples are present in LOD.

This is the canonical LS validator. It directly audits the saved rendered LS
premises, rather than approximating LS counterfactuality through a bidirectional
property check.

Important scope note: LS keeps some source-derived premise context by design.
Therefore this script does not require every rendered LS premise triple to be
absent from LOD. Instead, it audits the set difference:

    saved LS premise triples - original source/RK premise triples

Any premise triple already present in the original source entry is retained
context, even if it appears at a different premise position after the local
shuffle. Only shuffle-induced novel premise triples are checked for explicit LOD
presence.

Problem 1 — wrong predicate checked for the "_7-family" patterns (rdfs7,
rdfs2_7, rdfs3_7, rdfs2_3_7, rdfs5_7, rdfs2_5_7, rdfs3_5_7). LS shuffles the
property term(s) (i/j, or i/j/k) together with the instance subject/object, so
the instance triple LS actually renders uses a DIFFERENT property than the
source sample's `i` (it may be `j`, or after a 3-way derangement, `j` or `k`).
The old script always re-checked the original `i` (via source lod-sample
`i`/`i_dbp`), which is checking a triple LS never asserted. This script checks
the exact predicate that appears in the saved LS instance triple.

Problem 2 — non-reproducibility of `shuffle_terms` for 3-way derangements.
`_derange_list` picks between >=2 valid derangements; the file saved at
generation time is not guaranteed to match a fresh call (verified empirically:
re-running shuffle_terms mismatches the saved rdfs5_7 LS dataset in 206/400
premises). So which property (j or k) LS actually put in the instance slot
CANNOT be recovered by recomputing shuffle_terms — it must be read from the
saved LS dataset file directly.

Fix: read the *rendered* LS dataset (`data/datasets/ls/...`), parse each changed
premise triple, and resolve every rendered term against the corresponding
lod-sample entry. The source follows the shuffled surface term, not the rendered
slot name. DBpedia-sourced triples are checked on DBpedia; Wikidata property
instance triples resolve DBpedia subjects/objects to QIDs via explicit
owl:sameAs and then ASK the exact Wikidata direct property. No RDFS/OWL/schema
inference is applied.

Scope: all LS patterns. For each saved LS entry, the script reads the rendered
premise from disk, removes the original source premise triples as a set, and
ASK-checks only the remaining shuffle-induced premise triples. It does not
recompute shuffle_terms.

Usage:
    python3.10 scripts/validate-dataset/check_ls_counterfactual.py
        [--config scripts/validate-dataset/configs/ls-validation-config.json]
        [--patterns rdfs7,rdfs5_7,...] [--sleep SECONDS]
        [--out-root data/validation/ls]

Writes (one per pattern):
    data/validation/ls/{n}-rule/validation__ls__{pattern}__n{N}__{fetch_uid}__{build_uid}.json
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
sys.path.insert(0, THIS_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts", "build-dataset"))

import lod_query_helpers as lod  # noqa: E402
import rdfs_pattern_spec as pattern_spec  # noqa: E402
import validation_numeric as vnum  # noqa: E402
from shared._base import RULE_CONFIGS  # noqa: E402  (build_terms)

LOD_ROOT = os.path.join(PROJECT_ROOT, "data", "lod-samples")
DEFAULT_CONFIG = os.path.join(THIS_DIR, "configs", "ls-validation-config.json")
DEFAULT_OUT_ROOT = os.path.join(PROJECT_ROOT, "data", "validation", "ls")

WD_ENDPOINT = lod.WD_ENDPOINT
WDT_SUBPROPERTY_OF = "http://www.wikidata.org/prop/direct/P1647"
WDT_SUBCLASS_OF = "http://www.wikidata.org/prop/direct/P279"
WDT_INSTANCE_OF = "http://www.wikidata.org/prop/direct/P31"
SPARQL_TIMEOUT_SECONDS = lod.SPARQL_TIMEOUT_SECONDS
SPARQL_RETRIES = lod.SPARQL_RETRIES
SPARQL_BACKOFF_SECONDS = lod.SPARQL_BACKOFF_SECONDS
EMPTY_RESULT_CONFIRM_ATTEMPTS = lod.EMPTY_RESULT_CONFIRM_ATTEMPTS
QID_QUERY_ERROR_CACHE_SECONDS = lod.QID_QUERY_ERROR_CACHE_SECONDS
IDENTITY_POLICY = lod.IDENTITY_POLICY

# Instance-bearing LS patterns.
INSTANCE_PATTERNS = [
    "rdfs2", "rdfs3",
    "rdfs2_3", "rdfs2_7", "rdfs2_9", "rdfs3_7", "rdfs3_9", "rdfs5_7",
    "rdfs2_3_7", "rdfs2_3_9", "rdfs2_5_7", "rdfs2_9_11", "rdfs3_5_7", "rdfs3_9_11",
    "rdfs7",
]

PREMISE_PATTERNS = ["rdfs5", "rdfs9", "rdfs11", "rdfs9_11"]
TARGET_PATTERNS = INSTANCE_PATTERNS + PREMISE_PATTERNS

# For each pattern, which entry field supplies the TRUE source URI for each
# property term key produced by build_terms(). Derived from RULE_CONFIGS in
# scripts/build-dataset/shared/_base.py (verified against the actual lambdas,
# not guessed): most patterns use "i" (a native DBpedia property); the
# Wikidata-linked "_7-family" uses "i_dbp" for i and the raw Wikidata P-id
# field for j/k; rdfs2_7 is the one "_7" pattern that is pure DBpedia (i and j
# both raw DBpedia URIs).
PROP_SOURCE_FIELDS = {
    "rdfs2":      {"i": ("dbpedia", "i")},
    "rdfs3":      {"i": ("dbpedia", "i")},
    "rdfs2_3":    {"i": ("dbpedia", "i")},
    "rdfs2_9":    {"i": ("dbpedia", "i")},
    "rdfs3_9":    {"i": ("dbpedia", "i")},
    "rdfs2_3_9":  {"i": ("dbpedia", "i")},
    "rdfs2_9_11": {"i": ("dbpedia", "i")},
    "rdfs3_9_11": {"i": ("dbpedia", "i")},
    "rdfs2_7":    {"i": ("dbpedia", "i"), "j": ("dbpedia", "j")},
    "rdfs7":      {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j")},
    "rdfs3_7":    {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j")},
    "rdfs2_3_7":  {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j")},
    "rdfs5_7":    {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j"), "k": ("wikidata", "k")},
    "rdfs2_5_7":  {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j"), "k": ("wikidata", "k")},
    "rdfs3_5_7":  {"i": ("dbpedia", "i_dbp"), "j": ("wikidata", "j"), "k": ("wikidata", "k")},
    "rdfs5":      {"i": ("auto", "i"), "j": ("auto", "j"), "k": ("auto", "k")},
}


def resolve_lod_sample_from_dataset(
    pattern: str,
    dataset_rel_path: str,
    dataset_metadata: dict,
) -> tuple[str, str]:
    source_filename = dataset_metadata.get("source_filename")
    if not source_filename:
        raise KeyError(f"{pattern}: {dataset_rel_path} metadata has no source_filename")
    matches = glob.glob(os.path.join(LOD_ROOT, "*-rule", source_filename))
    if len(matches) != 1:
        raise FileNotFoundError(f"{pattern}: expected exactly 1 configured lod-sample {source_filename}, found {len(matches)}: {matches}")
    return os.path.relpath(matches[0], PROJECT_ROOT), matches[0]


def load_validation_config(config_path: str, patterns: list[str]) -> list[tuple[str, str, str, str, str]]:
    config = json.load(open(config_path, encoding="utf-8"))
    unknown = [p for p in patterns if p not in TARGET_PATTERNS]
    if unknown:
        raise SystemExit(f"unknown/unsupported patterns {unknown}; valid: {TARGET_PATTERNS}")
    missing = [p for p in patterns if p not in config]
    if missing:
        raise SystemExit(f"patterns missing from {config_path}: {missing}")
    out = []
    for pattern in patterns:
        rel_path = config[pattern]
        abs_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"{pattern}: configured LS dataset does not exist: {rel_path}")
        metadata = json.load(open(abs_path, encoding="utf-8"))["metadata"]
        if metadata["pattern_id"] != pattern:
            raise SystemExit(f"{rel_path}: config key {pattern} does not match metadata pattern {metadata['pattern_id']}")
        lod_rel_path, lod_abs_path = resolve_lod_sample_from_dataset(pattern, rel_path, metadata)
        out.append((pattern, rel_path, abs_path, lod_rel_path, lod_abs_path))
    return out


LocalUriMap = dict[str, list[tuple[str, str]]]


def _source_for_uri(uri: str) -> str:
    return "wikidata" if uri.startswith(lod.WD_ENTITY) else "dbpedia"


def _add_local_uri(votes: dict[str, set[tuple[str, str]]], name: str | None, uri: str | None, source: str) -> None:
    if name and uri:
        votes[name].add((lod.normalize_lod_uri(uri), source))


def _freeze_local_uri_map(votes: dict[str, set[tuple[str, str]]]) -> LocalUriMap:
    return {name: sorted(values) for name, values in votes.items()}


def build_entry_entity_map(pattern: str, source_entry: dict) -> LocalUriMap:
    """Rendered local instance name -> source URI for this exact lod-sample entry."""
    cfg = RULE_CONFIGS[pattern]
    terms = cfg["build_terms"](source_entry)
    votes: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for key in ("a", "b"):
        _add_local_uri(votes, terms.get(key), source_entry.get(key), "dbpedia")
    return _freeze_local_uri_map(votes)


def build_entry_prop_map(pattern: str, source_entry: dict) -> LocalUriMap:
    """Rendered local property name -> source URI for this exact lod-sample entry.

    The source follows the shuffled surface term, not the rendered slot name. This
    matters for 3-way LS derangements such as DBpedia/Wikidata/Wikidata i/j/k:
    after shuffling, the term rendered in the `i` slot may still be Wikidata-born.
    """
    spec = PROP_SOURCE_FIELDS.get(pattern, {})
    cfg = RULE_CONFIGS[pattern]
    terms = cfg["build_terms"](source_entry)
    votes: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for key, (source, field) in spec.items():
        uri = source_entry.get(field)
        actual_source = _source_for_uri(uri) if source == "auto" and uri else source
        _add_local_uri(votes, terms.get(key), uri, actual_source)
    return _freeze_local_uri_map(votes)


def build_entry_class_map(pattern: str, source_entry: dict) -> LocalUriMap:
    """Rendered local class name -> source URI for this exact lod-sample entry."""
    cfg = RULE_CONFIGS[pattern]
    terms = cfg["build_terms"](source_entry)
    votes: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for key, name in terms.items():
        if key and key[0] in "xyzw":
            uri = source_entry.get(key)
            _add_local_uri(votes, name, uri, _source_for_uri(uri) if uri else "dbpedia")
    return _freeze_local_uri_map(votes)


def resolve_wikidata_qids(dbr_uri: str, local_name: str):
    """DBpedia resource -> Wikidata QIDs. Cached.

    The validation uses only explicit LOD identity evidence. In particular,
    DBpedia resources are mapped to Wikidata entities only through owl:sameAs;
    page-level links such as dbo:wikiPageRedirects or Wikidata sitelinks are
    not treated as same-individual evidence.

    Intermediate nodes (see _is_intermediate_node) are skipped before querying:
    they cannot resolve by construction.

    Note: this only changes HOW an entity's QID is found. The validation
    semantics (which triple is checked, and against which property) are
    unchanged -- unlike a DBpedia-with-i fallback for the property side, which
    would silently re-introduce the exact problem this script fixes (see F4).
    """
    return lod.resolve_wikidata_qids(dbr_uri, local_name)


def _sameas_query_error_reason(*reasons: str | None) -> str | None:
    return lod.sameas_query_error_reason(*reasons)


def _qid_resolution_log(
    s_name: str,
    s_uri: str,
    s_qids,
    s_reason: str | None,
    s_log: dict | None,
    s_cache_hit: bool,
    o_name: str,
    o_uri: str,
    o_qids,
    o_reason: str | None,
    o_log: dict | None,
    o_cache_hit: bool,
) -> dict:
    return lod.qid_resolution_log(
        s_name,
        s_uri,
        s_qids,
        s_reason,
        s_log,
        s_cache_hit,
        o_name,
        o_uri,
        o_qids,
        o_reason,
        o_log,
        o_cache_hit,
    )


def _missing_qid_reason(s_qids, s_reason: str | None, o_qids, o_reason: str | None) -> str:
    return lod.missing_qid_reason(s_qids, s_reason, o_qids, o_reason)


def wd_direct_ask(s_qids: list[str], o_qids: list[str], p_wd_uri: str, label: str = "direct ASK"):
    """ASK whether the exact Wikidata direct property triple is present.

    This deliberately does not follow P1647/subPropertyOf or any other schema
    relation. The validation checks explicit LOD presence only.
    """
    return lod.wd_direct_ask(s_qids, o_qids, p_wd_uri, label=label)


def _qid_from_wd_entity_uri(uri: str) -> str | None:
    if uri.startswith(lod.WD_ENTITY):
        qid = uri[len(lod.WD_ENTITY):]
        if re.fullmatch(r"Q[1-9][0-9]*", qid):
            return qid
    return None


def _endpoint_name(endpoint: str | None) -> str:
    if endpoint == lod.WD_ENDPOINT:
        return "wikidata"
    if endpoint == lod.DBP_ENDPOINT:
        return "dbpedia"
    return "none"


def _ask_explicit_triple(endpoint: str, query: str, label: str):
    value, reason, query_log = lod.ask_endpoint(endpoint, query, label=label)
    return bool(value) if value is not None else None, reason, query_log


def _premise_role(triple: tuple[str, str, str]) -> str:
    pred = triple[1]
    if pred == "rdfs:subPropertyOf":
        return "subPropertyOf"
    if pred == "rdfs:subClassOf":
        return "subClassOf"
    if pred == "rdf:type":
        return "type"
    if pred == "rdfs:domain":
        return "domain"
    if pred == "rdfs:range":
        return "range"
    return "instance"


def _premise_uri(
    name: str,
    role_type: str,
    *,
    pattern: str,
    entity_map: LocalUriMap,
    prop_map: LocalUriMap,
    class_map: LocalUriMap,
) -> tuple[str | None, str | None, str | None]:
    def select(mapping: LocalUriMap, kind: str) -> tuple[str | None, str | None, str | None]:
        candidates = mapping.get(name)
        if not candidates:
            return None, None, f"{pattern}: unresolved {kind} name {name!r}"
        if len(candidates) > 1:
            rendered = ", ".join(f"{uri} ({source})" for uri, source in candidates)
            return None, None, f"{pattern}: ambiguous {kind} name {name!r}: {rendered}"
        uri, source = candidates[0]
        return uri, source, None

    if role_type == "entity":
        return select(entity_map, "entity")
    if role_type == "property":
        return select(prop_map, "property")
    if role_type == "class":
        return select(class_map, "class")
    raise ValueError(f"unknown role_type {role_type}")


def ask_premise_triple(
    *,
    pattern: str,
    entry_index_0based: int,
    triple_index_0based: int,
    triple: tuple[str, str, str],
    entity_map: LocalUriMap,
    prop_map: LocalUriMap,
    class_map: LocalUriMap,
) -> dict:
    """Direct ASK for one rendered LS premise triple.

    This checks exactly one shuffle-induced premise triple rendered in the saved
    LS dataset. It does not recompute the LS shuffle and does not apply any
    RDFS/OWL reasoning.
    """
    s_name, p_name, o_name = triple
    role = _premise_role(triple)

    base = {
        "triple_index_0based": triple_index_0based,
        "triple_index_1based": triple_index_0based + 1,
        "role": role,
        "triple": pattern_spec.triple_text(triple),
    }
    label = f"LS premise {pattern} entry {entry_index_0based + 1} triple {triple_index_0based + 1} {role}"

    if role == "subPropertyOf":
        s_uri, s_source, s_err = _premise_uri(
            s_name, "property", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        o_uri, o_source, o_err = _premise_uri(
            o_name, "property", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        if s_err or o_err:
            return {**base, "endpoint": "none", "query": None, "query_log": None, "explicitly_present": None, "reason": "; ".join(e for e in [s_err, o_err] if e)}
        if s_source == "wikidata" and o_source == "wikidata":
            query = f"ASK {{ <{s_uri}> <{WDT_SUBPROPERTY_OF}> <{o_uri}> }}"
            endpoint = lod.WD_ENDPOINT
        elif s_source != "wikidata" and o_source != "wikidata":
            query = f"ASK {{ <{s_uri}> <{lod.RDFS}subPropertyOf> <{o_uri}> }}"
            endpoint = lod.DBP_ENDPOINT
        else:
            return {
                **base,
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": "cross-KG subPropertyOf: absent by construction (no KG asserts a cross-namespace subproperty edge)",
                "s_uri": s_uri,
                "o_uri": o_uri,
            }

    elif role in ("domain", "range"):
        s_uri, _s_source, s_err = _premise_uri(
            s_name, "property", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        o_uri, _o_source, o_err = _premise_uri(
            o_name, "class", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        if s_err or o_err:
            return {**base, "endpoint": "none", "query": None, "query_log": None, "explicitly_present": None, "reason": "; ".join(e for e in [s_err, o_err] if e)}
        pred_uri = lod.RDFS + role
        if s_uri.startswith(lod.WD_ENTITY):
            # Wikidata properties do not use rdfs:domain/range as the benchmark source relation.
            return {
                **base,
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": f"Wikidata property {role}: absent by construction for explicit RDFS domain/range validation",
                "s_uri": s_uri,
                "o_uri": o_uri,
            }
        endpoint = lod.DBP_ENDPOINT
        query = f"ASK {{ <{s_uri}> <{pred_uri}> <{o_uri}> }}"

    elif role == "subClassOf":
        s_uri, s_source, s_err = _premise_uri(
            s_name, "class", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        o_uri, o_source, o_err = _premise_uri(
            o_name, "class", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        if s_err or o_err:
            return {**base, "endpoint": "none", "query": None, "query_log": None, "explicitly_present": None, "reason": "; ".join(e for e in [s_err, o_err] if e)}
        if s_source == "wikidata" and o_source == "wikidata":
            query = f"ASK {{ <{s_uri}> <{WDT_SUBCLASS_OF}> <{o_uri}> }}"
            endpoint = lod.WD_ENDPOINT
        elif s_source != "wikidata" and o_source != "wikidata":
            endpoint = lod.DBP_ENDPOINT
            query = f"ASK {{ <{s_uri}> <{lod.RDFS}subClassOf> <{o_uri}> }}"
        else:
            return {
                **base,
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": "cross-KG subClassOf: absent by construction (no KG asserts a cross-namespace subclass edge)",
                "s_uri": s_uri,
                "o_uri": o_uri,
            }

    elif role == "type":
        s_uri, s_source, s_err = _premise_uri(
            s_name, "entity", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        o_uri, o_source, o_err = _premise_uri(
            o_name, "class", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        if s_err or o_err:
            return {**base, "endpoint": "none", "query": None, "query_log": None, "explicitly_present": None, "reason": "; ".join(e for e in [s_err, o_err] if e)}
        if o_source == "wikidata":
            o_qid = _qid_from_wd_entity_uri(o_uri)
            if not o_qid:
                return {
                    **base,
                    "endpoint": "wikidata",
                    "query": None,
                    "query_log": None,
                    "explicitly_present": None,
                    "reason": f"Wikidata class URI is not a QID entity URI: {o_uri}",
                }
            s_qid = _qid_from_wd_entity_uri(s_uri)
            if s_qid:
                s_qids, s_reason, s_log, s_cache_hit = [s_qid], None, {"source": "wikidata_entity_uri"}, False
            else:
                s_qids, s_reason, s_log, s_cache_hit = resolve_wikidata_qids(s_uri, s_name)
            qid_resolution = {
                "subject": {
                    "name": s_name,
                    "dbpedia_uri": s_uri,
                    "qids": s_qids,
                    "reason": s_reason,
                    "query_log": s_log,
                    "cache_hit": s_cache_hit,
                },
                "object": {
                    "name": o_name,
                    "wikidata_uri": o_uri,
                    "qids": [o_qid],
                    "reason": None,
                    "query_log": None,
                    "cache_hit": False,
                },
            }
            if not s_qids:
                query_error = _sameas_query_error_reason(s_reason)
                if query_error:
                    return {
                        **base,
                        "endpoint": "wikidata",
                        "query": None,
                        "query_log": None,
                        "explicitly_present": None,
                        "reason": query_error,
                        "qid_resolution": qid_resolution,
                    }
                return {
                    **base,
                    "endpoint": "wikidata",
                    "query": None,
                    "query_log": None,
                    "explicitly_present": None,
                    "identity_unresolved": True,
                    "reason": _missing_qid_reason(s_qids, s_reason, [o_qid], None),
                    "qid_resolution": qid_resolution,
                }
            value, reason, query_log = wd_direct_ask(s_qids, [o_qid], WDT_INSTANCE_OF, label=label)
            return {
                **base,
                "endpoint": "wikidata",
                "query": query_log.get("query") if query_log else None,
                "query_log": query_log,
                "explicitly_present": value,
                "reason": reason,
                "qid_resolution": qid_resolution,
            }
        if s_source == "wikidata":
            return {
                **base,
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": "cross-KG rdf:type: absent by construction (Wikidata subject with DBpedia class)",
                "s_uri": s_uri,
                "o_uri": o_uri,
            }
        endpoint = lod.DBP_ENDPOINT
        query = f"ASK {{ <{s_uri}> <{lod.RDF}type> <{o_uri}> }}"

    elif role == "instance":
        s_uri, _s_source, s_err = _premise_uri(
            s_name, "entity", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        p_uri, p_source, p_err = _premise_uri(
            p_name, "property", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        o_uri, _o_source, o_err = _premise_uri(
            o_name, "entity", pattern=pattern, entity_map=entity_map, prop_map=prop_map, class_map=class_map
        )
        if s_err or p_err or o_err:
            return {**base, "endpoint": "none", "query": None, "query_log": None, "explicitly_present": None, "reason": "; ".join(e for e in [s_err, p_err, o_err] if e)}
        if p_source == "dbpedia":
            endpoint = lod.DBP_ENDPOINT
            query = f"ASK {{ <{s_uri}> <{p_uri}> <{o_uri}> }}"
        else:
            s_qids, s_reason, s_log, s_cache_hit = resolve_wikidata_qids(s_uri, s_name)
            o_qids, o_reason, o_log, o_cache_hit = resolve_wikidata_qids(o_uri, o_name)
            qid_resolution = _qid_resolution_log(
                s_name, s_uri, s_qids, s_reason, s_log, s_cache_hit,
                o_name, o_uri, o_qids, o_reason, o_log, o_cache_hit,
            )
            if not s_qids or not o_qids:
                query_error = _sameas_query_error_reason(
                    s_reason if not s_qids else None,
                    o_reason if not o_qids else None,
                )
                if query_error:
                    return {
                        **base,
                        "endpoint": "wikidata",
                        "query": None,
                        "query_log": None,
                        "explicitly_present": None,
                        "reason": query_error,
                        "qid_resolution": qid_resolution,
                    }
                return {
                    **base,
                    "endpoint": "wikidata",
                    "query": None,
                    "query_log": None,
                    "explicitly_present": None,
                    "identity_unresolved": True,
                    "reason": _missing_qid_reason(s_qids, s_reason, o_qids, o_reason),
                    "qid_resolution": qid_resolution,
                }
            value, reason, query_log = wd_direct_ask(s_qids, o_qids, p_uri, label=label)
            return {
                **base,
                "endpoint": "wikidata",
                "query": query_log.get("query") if query_log else None,
                "query_log": query_log,
                "explicitly_present": value,
                "reason": reason,
                "qid_resolution": qid_resolution,
            }

    else:
        return {
            **base,
            "endpoint": "none",
            "query": None,
            "query_log": None,
            "explicitly_present": None,
            "reason": f"unexpected premise role for shuffle-induced LS audit: {role}",
        }

    value, reason, query_log = _ask_explicit_triple(endpoint, query, label)
    return {
        **base,
        "endpoint": _endpoint_name(endpoint),
        "query": query,
        "query_log": query_log,
        "explicitly_present": value,
        "reason": reason,
    }


def _meta_from_path(rel_path: str) -> dict:
    fname = os.path.basename(rel_path)  # dataset__ls__rdfs7__n400__f-xxx__b-yyy.json
    n_rule_dir = os.path.basename(os.path.dirname(rel_path))
    n = re.search(r"__n(\d+)__", fname)
    fetch_uid = re.search(r"__(f-[0-9a-f]+)__", fname)
    build_uid = re.search(r"__(b-[0-9a-f]+)\.json$", fname)
    out_name = fname.replace("dataset__ls__", "validation__ls__", 1)
    return {
        "n_rule_dir": n_rule_dir,
        "n": int(n.group(1)) if n else None,
        "fetch_uid": fetch_uid.group(1) if fetch_uid else None,
        "build_uid": build_uid.group(1) if build_uid else None,
        "out_name": out_name,
    }


def source_premise_triples(pattern: str, source_entry: dict) -> list[tuple[str, str, str]]:
    """Original source/RK premise triples for this exact lod-sample entry.

    LS validation excludes these triples as retained premise context. The
    comparison is set-based, not position-based, because local shuffle can move
    an unchanged source triple to a different premise position.
    """
    cfg = RULE_CONFIGS[pattern]
    terms = cfg["build_terms"](source_entry)
    return pattern_spec.parse_triples(cfg["build_premise"](terms))


def shuffle_induced_premise_triples(
    pattern: str,
    source_entry: dict,
    rendered_ls_triples: list[tuple[str, str, str]],
) -> tuple[list[tuple[int, tuple[str, str, str]]], list[tuple[str, str, str]]]:
    source_triples = source_premise_triples(pattern, source_entry)
    source_set = set(source_triples)
    return [(i, tri) for i, tri in enumerate(rendered_ls_triples) if tri not in source_set], source_triples


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--patterns", default="",
                    help="comma-separated subset of LS validation patterns (for parallel splitting)")
    args = ap.parse_args()

    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()] or TARGET_PATTERNS
    all_configured_files = load_validation_config(args.config, TARGET_PATTERNS)
    configured_files = load_validation_config(args.config, patterns)
    _configured_patterns = {pattern for pattern, *_rest in all_configured_files}
    if set(TARGET_PATTERNS) != _configured_patterns:
        raise SystemExit("internal config load mismatch for LS target patterns")

    changed_plan = []  # (pattern, rel_path, lod_rel_path, meta, [entry_check_plan, ...])
    for pattern, rel_path, abs_path, lod_rel_path, _lod_abs_path in configured_files:
        entries = json.load(open(abs_path, encoding="utf-8"))["entries"]
        source_entries = json.load(open(_lod_abs_path, encoding="utf-8"))["entries"]
        if len(entries) != len(source_entries):
            raise SystemExit(f"{pattern}: LS dataset has {len(entries)} entries but source lod-sample has {len(source_entries)}")
        roles = pattern_spec.PATTERN_SPEC[pattern]
        if pattern not in TARGET_PATTERNS:
            raise SystemExit(f"{pattern}: unsupported LS validation pattern")
        items = []
        for e, source_entry in zip(entries, source_entries):
            triples = pattern_spec.parse_triples(e["premise_knowledge"])
            source_triples = source_premise_triples(pattern, source_entry)
            if len(triples) != len(roles) or len(source_triples) != len(roles):
                items.append(None)  # structural mismatch; counted as error below
                continue
            audit_triples, source_triples = shuffle_induced_premise_triples(pattern, source_entry, triples)
            items.append({
                "changed_triples": audit_triples,
                "source_premise_triples": source_triples,
                "entity_map": build_entry_entity_map(pattern, source_entry),
                "prop_map": build_entry_prop_map(pattern, source_entry),
                "class_map": build_entry_class_map(pattern, source_entry),
            })
        changed_plan.append((pattern, rel_path, lod_rel_path, _meta_from_path(rel_path), items))

    grand_total = sum(len(items) for _, _, _, _, items in changed_plan)
    done = 0
    overall = {
        "judged": 0,
        "lod_checked": 0,
        "explicitly_present": 0,
        "explicitly_absent": 0,
        "identity_unresolved": 0,
        "errors": 0,
    }

    for pattern, rel_path, lod_rel_path, meta, items in changed_plan:
        lod_checked = explicitly_present = explicitly_absent = identity_unresolved = errors = 0
        hit_examples = []
        explicitly_absent_examples = []
        identity_unresolved_examples = []
        error_examples = []

        for entry_index_0based, entry_plan in enumerate(items):
            entry_index_1based = entry_index_0based + 1
            done += 1
            remaining = grand_total - done
            base = {
                "pattern_id": pattern,
                "entry_index_0based": entry_index_0based,
                "entry_index_1based": entry_index_1based,
            }

            if entry_plan is None:
                errors += 1
                error_examples.append({
                    **base,
                    "reason": "premise did not match PATTERN_SPEC arity",
                })
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} PREMISE-STRUCTURAL-ERROR | remaining {remaining}")
                continue

            changed_triples = entry_plan["changed_triples"]
            triple_checks = []
            for original_triple_index_0based, tri in changed_triples:
                check = ask_premise_triple(
                    pattern=pattern,
                    entry_index_0based=entry_index_0based,
                    triple_index_0based=original_triple_index_0based,
                    triple=tri,
                    entity_map=entry_plan["entity_map"],
                    prop_map=entry_plan["prop_map"],
                    class_map=entry_plan["class_map"],
                )
                triple_checks.append(check)
                status = check["explicitly_present"]
                if status is True:
                    verdict = "present"
                elif status is False:
                    verdict = "absent"
                else:
                    verdict = f"ERROR ({check.get('reason')})"
                lod._log(
                    f"[ {done}/{grand_total} ] {pattern:12} "
                    f"{check['triple']} -> {verdict} | remaining {remaining}"
                )
                time.sleep(args.sleep)

            present_checks = [c for c in triple_checks if c["explicitly_present"] is True]
            unresolved_checks = [c for c in triple_checks if c["explicitly_present"] is None and c.get("identity_unresolved")]
            error_checks = [c for c in triple_checks if c["explicitly_present"] is None and not c.get("identity_unresolved")]
            premise_triples = [pattern_spec.triple_text(t) for _i, t in changed_triples]
            source_premise = [pattern_spec.triple_text(t) for t in entry_plan["source_premise_triples"]]

            if present_checks:
                lod_checked += 1
                explicitly_present += 1
                hit_examples.append({
                    **base,
                    "shuffle_induced_premise_triples": premise_triples,
                    "source_premise_triples": source_premise,
                    "reason": "at least one shuffle-induced LS premise triple is explicitly present in LOD",
                    "present_triples": present_checks,
                    "nonblocking_identity_unresolved": unresolved_checks,
                    "nonblocking_query_errors": error_checks,
                    "triple_checks": triple_checks,
                })
                entry_verdict = "CONTAMINATED (shuffle-induced premise triple present)"
            # Verdict priority is present > identity-unresolved > error, matching
            # the GS/GSC validators so that the "why was this entry not judged"
            # breakdown is comparable across variants.
            elif unresolved_checks:
                identity_unresolved += 1
                identity_unresolved_examples.append({
                    **base,
                    "shuffle_induced_premise_triples": premise_triples,
                    "source_premise_triples": source_premise,
                    "reason": "one or more shuffle-induced premise instance triples could not be resolved to Wikidata QIDs and no explicit-present triple was found",
                    "identity_unresolved_triples": unresolved_checks,
                    "nonblocking_query_errors": error_checks,
                    "triple_checks": triple_checks,
                })
                entry_verdict = "IDENTITY-UNRESOLVED"
            elif error_checks:
                errors += 1
                error_examples.append({
                    **base,
                    "shuffle_induced_premise_triples": premise_triples,
                    "source_premise_triples": source_premise,
                    "reason": "one or more shuffle-induced premise triple checks failed and no explicit-present triple was found",
                    "error_triples": error_checks,
                    "triple_checks": triple_checks,
                })
                entry_verdict = "ERROR"
            else:
                lod_checked += 1
                explicitly_absent += 1
                explicitly_absent_examples.append({
                    **base,
                    "shuffle_induced_premise_triples": premise_triples,
                    "source_premise_triples": source_premise,
                    "reason": "all shuffle-induced LS premise triples are explicitly absent from LOD",
                    "triple_checks": triple_checks,
                })
                entry_verdict = "counterfactual"

            lod._log(f"[ {done}/{grand_total} ] {pattern:12} entry {entry_index_1based} -> {entry_verdict} | remaining {remaining}")

        cf = explicitly_absent
        judged = lod_checked
        out = {
            "metadata": {
                "validation_type": "ls_shuffle_induced_premise_explicit_lod_presence",
                "granularity": "shuffle_induced_premise_triples",
                "check": (
                    "Parse the saved rendered LS premise, subtract the original "
                    "source/RK premise triples as a set, and directly ASK every "
                    "remaining shuffle-induced premise triple. Source premise triples "
                    "retained by LS are excluded even if they move to a different "
                    "premise position. One explicit true shuffle-induced premise "
                    "triple contaminates the entry; all false means counterfactual. "
                    "The LS shuffle is not recomputed, and no RDFS/OWL inference, "
                    "subClassOf/subPropertyOf closure, redirects, or sitelink fallback "
                    "is used."
                ),
                "input": "rendered LS dataset",
                "source_dataset": rel_path,
                "source_lod_sample": lod_rel_path,
                "validation_config": os.path.relpath(args.config, PROJECT_ROOT),
                "pattern_id": pattern,
                "fetch_uid": meta["fetch_uid"],
                "build_uid": meta["build_uid"],
                "n": meta["n"],
                "identity_policy": IDENTITY_POLICY,
                "logging_policy": (
                    "Every emitted example stores the rendered premise triples, "
                    "per-triple endpoint, SPARQL query, selected response headers, "
                    "and per-attempt query log."
                ),
                "dbpedia_endpoint": lod.DBP_ENDPOINT,
                "wikidata_endpoint": WD_ENDPOINT,
                "query_retry_policy": {
                    "timeout_seconds": SPARQL_TIMEOUT_SECONDS,
                    "dbpedia_server_timeout_ms": SPARQL_TIMEOUT_SECONDS * 1000,
                    "wikidata_server_timeout_ms": None,
                    "wikidata_timeout_policy": (
                        "Wikidata/Blazegraph receives only the client-side HTTP timeout; "
                        "the Virtuoso server-side timeout parameter is sent only to DBpedia"
                    ),
                    "max_retries": SPARQL_RETRIES,
                    "empty_result_confirm_attempts": EMPTY_RESULT_CONFIRM_ATTEMPTS,
                    "qid_query_error_cache_seconds": QID_QUERY_ERROR_CACHE_SECONDS,
                    "backoff_seconds": SPARQL_BACKOFF_SECONDS,
                    "backoff": "exponential",
                    "partial_result_headers": list(lod.PARTIAL_RESULT_HEADER_NAMES),
                    "partial_result_handling": (
                        "responses with Virtuoso/DBpedia partial-result headers "
                        "are retried and are not accepted as evidence of absence"
                    ),
                },
                "result_schema": (
                    "judged is the counterfactual-rate denominator. For LS shuffle-induced-premise "
                    "audit, judged == lod_checked == explicitly_present + explicitly_absent; "
                    "identity_unresolved and errors are excluded. explicitly_present means "
                    "at least one shuffle-induced premise triple was explicitly present in LOD. "
                    "Counts are canonical; *_rate_fraction and *_rate_decimal are derived "
                    "from the integer counts. No binary-float rate is serialized."
                ),
                "validated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "result": {
                "total": len(items),
                "judged": judged,
                "lod_checked": lod_checked,
                "explicitly_present": explicitly_present,
                "explicitly_absent": explicitly_absent,
                "identity_unresolved": identity_unresolved,
                "errors": errors,
                "shuffle_induced_counterfactual": cf,
                "shuffle_induced_counterfactual_rate_fraction": vnum.rate_fraction_str(cf, judged),
                "shuffle_induced_counterfactual_rate_decimal": vnum.rate_decimal_str(cf, judged),
                "counterfactual": cf,
                "counterfactual_rate_fraction": vnum.rate_fraction_str(cf, judged),
                "counterfactual_rate_decimal": vnum.rate_decimal_str(cf, judged),
                "contaminated": explicitly_present,
                "hit_examples": hit_examples,
                "explicitly_absent_examples": explicitly_absent_examples,
                "identity_unresolved_examples": identity_unresolved_examples,
                "error_examples": error_examples,
            },
        }
        out_dir = os.path.join(args.out_root, meta["n_rule_dir"])
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, meta["out_name"])
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        rate = f"{cf}/{judged}={cf/judged:.1%}" if judged else "n/a"
        lod._log(
            f"  -> {pattern}: confirmed shuffle-induced-premise counterfactual {rate} "
            f"(explicitly_present={explicitly_present}, identity_unresolved={identity_unresolved}, errors={errors}) "
            f"written {out_path}"
        )

        overall["judged"] += judged
        overall["lod_checked"] += lod_checked
        overall["explicitly_present"] += explicitly_present
        overall["explicitly_absent"] += explicitly_absent
        overall["identity_unresolved"] += identity_unresolved
        overall["errors"] += errors

    lod._log("\n=== overall ===")
    judged = overall["judged"]
    cf = overall["explicitly_absent"]
    lod._log(
        f"judged={judged} lod_checked={overall['lod_checked']} "
        f"explicitly_present={overall['explicitly_present']} "
        f"explicitly_absent={overall['explicitly_absent']} "
        f"identity_unresolved={overall['identity_unresolved']} errors={overall['errors']}"
    )
    if judged:
        lod._log(f"counterfactual rate: {cf}/{judged} = {cf/judged:.1%}")


if __name__ == "__main__":
    main()
