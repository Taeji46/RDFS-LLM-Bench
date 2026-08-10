"""Shared helpers for GS/GSC explicit-LOD validators.

This module contains only the behavior that is identical for GS and GSC:
pattern slot definitions, resource-type classification, URI recovery from a
source lod-sample entry, direct ASK construction, and per-triple LOD checks.

Variant-specific source binding remains in each validator:
  - GS matches rendered raw local names directly.
  - GSC enumerates raw_unicode case-converted interpretations.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
sys.path.insert(0, THIS_DIR)

import lod_query_helpers as lod  # noqa: E402
import rdfs_pattern_spec as pattern_spec  # noqa: E402

LOD_ROOT = os.path.join(PROJECT_ROOT, "data", "lod-samples")

WD_PREFIX = "http://www.wikidata.org/entity/"
WDT_SUBPROPERTY_OF = "http://www.wikidata.org/prop/direct/P1647"
WDT_SUBCLASS_OF = "http://www.wikidata.org/prop/direct/P279"
WDT_INSTANCE_OF = "http://www.wikidata.org/prop/direct/P31"


PATTERN_TRIPLE_KEYS = {
    "rdfs2": [("i", None, "x"), ("a", "i", "b")],
    "rdfs3": [("i", None, "x"), ("a", "i", "b")],
    "rdfs5": [("i", None, "j"), ("j", None, "k")],
    "rdfs7": [("i", None, "j"), ("a", "i", "b")],
    "rdfs9": [("x", None, "y"), ("a", None, "x")],
    "rdfs11": [("x", None, "y"), ("y", None, "z")],
    "rdfs2_3": [("i", None, "x"), ("i", None, "y"), ("a", "i", "b")],
    "rdfs2_7": [("i", None, "x"), ("i", None, "j"), ("a", "i", "b")],
    "rdfs2_9": [("i", None, "x"), ("x", None, "y"), ("a", "i", "b")],
    "rdfs3_7": [("i", None, "x"), ("i", None, "j"), ("a", "i", "b")],
    "rdfs3_9": [("i", None, "x"), ("x", None, "y"), ("a", "i", "b")],
    "rdfs5_7": [("i", None, "j"), ("j", None, "k"), ("a", "i", "b")],
    "rdfs9_11": [("x", None, "y"), ("y", None, "z"), ("a", None, "x")],
    "rdfs2_3_7": [("i", None, "x"), ("i", None, "y"), ("i", None, "j"), ("a", "i", "b")],
    "rdfs2_3_9": [("i", None, "x"), ("i", None, "y"), ("x", None, "z"), ("y", None, "w"), ("a", "i", "b")],
    "rdfs2_5_7": [("i", None, "x"), ("i", None, "j"), ("j", None, "k"), ("a", "i", "b")],
    "rdfs2_9_11": [("i", None, "x"), ("x", None, "y"), ("y", None, "z"), ("a", "i", "b")],
    "rdfs3_5_7": [("i", None, "x"), ("i", None, "j"), ("j", None, "k"), ("a", "i", "b")],
    "rdfs3_9_11": [("i", None, "x"), ("x", None, "y"), ("y", None, "z"), ("a", "i", "b")],
}

ROLE_EXPECT = {
    "domain": {0: "P", 2: "C"},
    "range": {0: "P", 2: "C"},
    "subClassOf": {0: "C", 2: "C"},
    "subPropertyOf": {0: "P", 2: "P"},
    "type": {0: "I", 2: "C"},
    "instance": {0: "I", 1: "P", 2: "I"},
}

PROP_URI_FIELDS = {
    "rdfs7": {"i": "i_dbp", "j": "j"},
    "rdfs3_7": {"i": "i_dbp", "j": "j"},
    "rdfs2_3_7": {"i": "i_dbp", "j": "j"},
    "rdfs5_7": {"i": "i_dbp", "j": "j", "k": "k"},
    "rdfs2_5_7": {"i": "i_dbp", "j": "j", "k": "k"},
    "rdfs3_5_7": {"i": "i_dbp", "j": "j", "k": "k"},
}


def keytype(key: str) -> str:
    base = key[0]
    if base in "ab":
        return "I"
    if base in "ijk":
        return "P"
    if base in "xyzw":
        return "C"
    return "?"


def infer_role(triple: tuple[str, str, str]) -> str:
    pred = triple[1]
    if pred == "rdfs:domain":
        return "domain"
    if pred == "rdfs:range":
        return "range"
    if pred == "rdfs:subClassOf":
        return "subClassOf"
    if pred == "rdfs:subPropertyOf":
        return "subPropertyOf"
    if pred == "rdf:type":
        return "type"
    return "instance"


def load_validation_config(
    config_path: str,
    patterns: list[str] | None,
    *,
    variant: str,
) -> list[tuple[str, str, str]]:
    config = json.load(open(config_path, encoding="utf-8"))
    selected_patterns = [p.strip() for p in patterns if p.strip()] if patterns else list(config.keys())
    missing = [p for p in selected_patterns if p not in config]
    if missing:
        raise SystemExit(f"patterns missing from {config_path}: {missing}")
    out = []
    for pattern in selected_patterns:
        rel_path = config[pattern]
        abs_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"{pattern}: configured {variant.upper()} dataset does not exist: {rel_path}")
        out.append((pattern, rel_path, abs_path))
    return out


def meta_from_path(rel_path: str, *, variant: str) -> dict:
    fname = os.path.basename(rel_path)
    n_rule_dir = os.path.basename(os.path.dirname(rel_path))
    n = re.search(r"__n(\d+)__", fname)
    fetch_uid = re.search(r"__(f-[0-9a-f]+)", fname)
    build_uid = re.search(r"__(b-[0-9a-f]+)\.json$", fname)
    out_name = fname.replace(f"dataset__{variant}__", f"validation__{variant}__", 1)
    return {
        "n_rule_dir": n_rule_dir,
        "n": int(n.group(1)) if n else None,
        "fetch_uid": fetch_uid.group(1) if fetch_uid else None,
        "build_uid": build_uid.group(1) if build_uid else None,
        "out_name": out_name,
    }


def source_lod_path(dataset_rel_path: str, dataset_metadata: dict) -> tuple[str, str]:
    source_filename = dataset_metadata.get("source_filename")
    if not source_filename:
        raise KeyError(f"{dataset_rel_path}: metadata has no source_filename")
    matches = glob.glob(os.path.join(LOD_ROOT, "*-rule", source_filename))
    if len(matches) == 1:
        return os.path.relpath(matches[0], PROJECT_ROOT), matches[0]
    pattern = dataset_metadata["pattern_id"]
    raise FileNotFoundError(f"{pattern}: expected exactly 1 configured lod-sample {source_filename}, found {len(matches)}")


def source_uri(pattern: str, origin_key: str, source_entry: dict) -> str:
    if keytype(origin_key) == "P":
        field = PROP_URI_FIELDS.get(pattern, {}).get(origin_key, origin_key)
        return lod.normalize_lod_uri(source_entry[field])
    return lod.normalize_lod_uri(source_entry[origin_key])


def hierarchy_uri(origin_key: str, source_entry: dict) -> str | None:
    if keytype(origin_key) != "P":
        return None
    return lod.normalize_lod_uri(source_entry[origin_key])


def extract_dest_terms(pattern: str, triples: list[tuple[str, str, str]]) -> dict[str, str]:
    slots = PATTERN_TRIPLE_KEYS[pattern]
    if len(slots) != len(triples):
        raise ValueError(f"{pattern}: expected {len(slots)} triples, got {len(triples)}")
    terms: dict[str, str] = {}
    for slot_keys, triple in zip(slots, triples):
        for pos, dest_key in enumerate(slot_keys):
            if dest_key is None:
                continue
            value = triple[pos]
            previous = terms.get(dest_key)
            if previous is not None and previous != value:
                raise ValueError(f"{pattern}: inconsistent rendered term for key {dest_key}: {previous} vs {value}")
            terms[dest_key] = value
    return terms


def binding_signature(bindings: dict[str, dict]) -> tuple:
    return tuple(
        (
            key,
            bindings[key]["origin_key"],
            bindings[key]["origin_type"],
            bindings[key]["uri"],
            bindings[key]["hierarchy_uri"],
        )
        for key in sorted(bindings)
    )


def classify_triples(pattern: str, triples: list[tuple[str, str, str]], bindings: dict[str, dict]) -> tuple[bool, list[dict]]:
    """Per-triple structural type-compatibility.

    The first return value reports whether EVERY premise triple is
    type-compatible.  It must not be read as "this entry is counterfactual":
    a type-incompatible triple only proves that THAT triple is absent from
    LOD, never that its sibling triples are.  Callers decide the entry verdict
    from the per-triple list -- see ``compatible_triple_indices``.
    """
    roles = [infer_role(triple) for triple in triples]
    slots = PATTERN_TRIPLE_KEYS[pattern]
    per_triple = []
    premise_ok = True
    for triple_index, (role, triple, slot_keys) in enumerate(zip(roles, triples, slots)):
        expected = ROLE_EXPECT[role]
        mismatches = []
        slot_details = []
        for pos, dest_key in enumerate(slot_keys):
            if dest_key is None:
                continue
            binding = bindings[dest_key]
            want = expected.get(pos)
            compatible = want is None or binding["origin_type"] == want
            if not compatible:
                mismatches.append({
                    "position": pos,
                    "expected": want,
                    "actual": binding["origin_type"],
                    "dest_key": dest_key,
                    "rendered": binding["rendered"],
                    "origin_key": binding["origin_key"],
                })
            slot_details.append({
                "position": pos,
                "dest_key": dest_key,
                "rendered": binding["rendered"],
                "expected_type": want,
                "origin_key": binding["origin_key"],
                "origin_type": binding["origin_type"],
                "uri": binding["uri"],
                "source": binding["source"],
                "compatible": compatible,
            })
        compatible = not mismatches
        if not compatible:
            premise_ok = False
        per_triple.append({
            "triple_index": triple_index,
            "role": role,
            "triple": pattern_spec.triple_text(triple),
            "compatible": compatible,
            "slots": slot_details,
            "mismatches": mismatches,
        })
    return premise_ok, per_triple


def compatible_triple_indices(per_triple: list[dict]) -> list[int]:
    """Indices of premise triples that still need an explicit LOD check.

    Type-incompatible triples are absent by construction (a resource whose
    original type does not match its rendered position cannot occur in that
    position in the source KG), so they need no query.  Every remaining triple
    must be asked before the entry can be called counterfactual.
    """
    return [t["triple_index"] for t in per_triple if t["compatible"]]


def _uri_for_slot(bindings: dict[str, dict], key: str) -> str:
    return bindings[key]["uri"]


def _schema_query(role: str, slot_keys: tuple[str | None, str | None, str | None], bindings: dict[str, dict]):
    """ASK query for a schema triple, or ``(None, None)`` if absent by construction.

    Each graph must be asked with its own vocabulary: DBpedia asserts the RDFS
    predicates, whereas Wikidata expresses the same relations through
    ``wdt:P279`` (subclass of) and ``wdt:P31`` (instance of).  A triple whose
    two terms come from different graphs cannot be asserted verbatim in either
    of them, and Wikidata never asserts ``rdfs:domain``/``rdfs:range`` at all,
    so those cases need no query.
    """
    s_key, _p_key, o_key = slot_keys
    s_uri = _uri_for_slot(bindings, s_key)
    o_uri = _uri_for_slot(bindings, o_key)
    s_wd = s_uri.startswith(WD_PREFIX)
    o_wd = o_uri.startswith(WD_PREFIX)

    if role in ("domain", "range"):
        if s_wd or o_wd:
            return None, None
        return f"ASK {{ <{s_uri}> <{lod.RDFS}{role}> <{o_uri}> }}", lod.DBP_ENDPOINT

    wd_pred = {"subClassOf": WDT_SUBCLASS_OF, "type": WDT_INSTANCE_OF}[role]
    dbp_pred = {"subClassOf": lod.RDFS + "subClassOf", "type": lod.RDF + "type"}[role]
    if s_wd and o_wd:
        return f"ASK {{ <{s_uri}> <{wd_pred}> <{o_uri}> }}", lod.WD_ENDPOINT
    if not s_wd and not o_wd:
        return f"ASK {{ <{s_uri}> <{dbp_pred}> <{o_uri}> }}", lod.DBP_ENDPOINT
    return None, None


def _subproperty_query(slot_keys: tuple[str | None, str | None, str | None], bindings: dict[str, dict]):
    s_uri = bindings[slot_keys[0]]["hierarchy_uri"]
    o_uri = bindings[slot_keys[2]]["hierarchy_uri"]
    s_wd = s_uri.startswith(WD_PREFIX)
    o_wd = o_uri.startswith(WD_PREFIX)
    if s_wd and o_wd:
        return f"ASK {{ <{s_uri}> <{WDT_SUBPROPERTY_OF}> <{o_uri}> }}", lod.WD_ENDPOINT
    if not s_wd and not o_wd:
        return f"ASK {{ <{s_uri}> <{lod.RDFS}subPropertyOf> <{o_uri}> }}", lod.DBP_ENDPOINT
    return None, None


def _dbpedia_instance_query(slot_keys: tuple[str, str, str], bindings: dict[str, dict]) -> str:
    s_uri = _uri_for_slot(bindings, slot_keys[0])
    p_uri = _uri_for_slot(bindings, slot_keys[1])
    o_uri = _uri_for_slot(bindings, slot_keys[2])
    return f"ASK {{ <{s_uri}> <{p_uri}> <{o_uri}> }}"


def ask_triple(
    *,
    variant_label: str,
    pattern: str,
    entry_index_0based: int,
    role: str,
    triple: tuple[str, str, str],
    slot_keys: tuple[str | None, str | None, str | None],
    bindings: dict[str, dict],
):
    label = f"{variant_label} {pattern} entry {entry_index_0based + 1} {role}"
    if role == "subPropertyOf":
        query, endpoint = _subproperty_query(slot_keys, bindings)
        if query is None:
            return {
                "role": role,
                "triple": pattern_spec.triple_text(triple),
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": "cross-KG subPropertyOf: absent by construction (no KG asserts a cross-namespace subproperty edge)",
            }
        value, reason, query_log = lod.ask_endpoint(endpoint, query, label=label)
        return {
            "role": role,
            "triple": pattern_spec.triple_text(triple),
            "endpoint": "wikidata" if endpoint == lod.WD_ENDPOINT else "dbpedia",
            "query": query,
            "query_log": query_log,
            "explicitly_present": bool(value) if value is not None else None,
            "reason": reason,
        }

    if role != "instance":
        query, endpoint = _schema_query(role, slot_keys, bindings)
        if query is None:
            if role in ("domain", "range"):
                why = (
                    f"{role} edge involving a Wikidata term: absent by construction "
                    "(Wikidata does not assert rdfs:domain/rdfs:range)"
                )
            else:
                why = (
                    f"cross-KG {role}: absent by construction "
                    "(no KG asserts this edge across namespaces)"
                )
            return {
                "role": role,
                "triple": pattern_spec.triple_text(triple),
                "endpoint": "none",
                "query": None,
                "query_log": None,
                "explicitly_present": False,
                "reason": why,
            }
        value, reason, query_log = lod.ask_endpoint(endpoint, query, label=label)
        return {
            "role": role,
            "triple": pattern_spec.triple_text(triple),
            "endpoint": "wikidata" if endpoint == lod.WD_ENDPOINT else "dbpedia",
            "query": query,
            "query_log": query_log,
            "explicitly_present": bool(value) if value is not None else None,
            "reason": reason,
        }

    p_uri = _uri_for_slot(bindings, slot_keys[1])
    if not p_uri.startswith(WD_PREFIX):
        query = _dbpedia_instance_query(slot_keys, bindings)
        value, reason, query_log = lod.ask_endpoint(lod.DBP_ENDPOINT, query, label=label)
        return {
            "role": role,
            "triple": pattern_spec.triple_text(triple),
            "endpoint": "dbpedia",
            "query": query,
            "query_log": query_log,
            "explicitly_present": bool(value) if value is not None else None,
            "reason": reason,
        }

    s_binding = bindings[slot_keys[0]]
    o_binding = bindings[slot_keys[2]]
    s_qids, s_reason, s_log, s_cache_hit = lod.resolve_wikidata_qids(s_binding["uri"], s_binding["rendered"])
    o_qids, o_reason, o_log, o_cache_hit = lod.resolve_wikidata_qids(o_binding["uri"], o_binding["rendered"])
    qid_resolution = lod.qid_resolution_log(
        s_binding["rendered"],
        s_binding["uri"],
        s_qids,
        s_reason,
        s_log,
        s_cache_hit,
        o_binding["rendered"],
        o_binding["uri"],
        o_qids,
        o_reason,
        o_log,
        o_cache_hit,
    )
    if not s_qids or not o_qids:
        return {
            "role": role,
            "triple": pattern_spec.triple_text(triple),
            "endpoint": "wikidata",
            "query": None,
            "query_log": None,
            "explicitly_present": None,
            "reason": lod.missing_qid_reason(s_qids, s_reason, o_qids, o_reason),
            "qid_resolution": qid_resolution,
            "identity_unresolved": True,
        }
    value, reason, query_log = lod.wd_direct_ask(s_qids, o_qids, p_uri, label=label)
    return {
        "role": role,
        "triple": pattern_spec.triple_text(triple),
        "endpoint": "wikidata",
        "query": query_log.get("query") if query_log else None,
        "query_log": query_log,
        "explicitly_present": bool(value) if value is not None else None,
        "reason": reason,
        "qid_resolution": qid_resolution,
    }
