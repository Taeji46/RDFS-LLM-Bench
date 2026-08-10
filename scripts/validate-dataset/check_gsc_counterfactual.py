"""Validate GSC premises for explicit LOD contamination.

Scope: this script validates only GSC (Global Shuffle + Case conversion).

GSC uses the same contamination policy as GS, but source recovery accounts for
the saved GSC rendering: each shuffled term is rendered with raw_unicode case
conversion according to its destination slot type.

GSC first receives a per-triple structural check: a term appearing in a position
whose resource type is impossible for that position makes THAT triple absent by
construction, so it needs no query. A type-incompatible triple never licenses a
verdict on its siblings, and a candidate interpretation counts as counterfactual
only once every remaining triple has been asked and found absent.

Structurally type-compatible triples are checked against LOD. The check is
direct ASK only, and each graph is asked with its own vocabulary:
  - DBpedia/schema.org triples are ASKed on DBpedia with the RDFS/RDF predicate.
  - Wikidata schema triples are ASKed on Wikidata with the corresponding direct
    property: P1647 (subPropertyOf), P279 (subClassOf), P31 (type).
  - A schema triple whose two terms come from different graphs, and any
    domain/range edge involving a Wikidata term, cannot be asserted verbatim in
    either graph and is treated as absent by construction without a query.
  - Instance triples with a Wikidata property are checked like LS: subject and
    object DBpedia resources are resolved through explicit owl:sameAs only, then
    the exact wdt:P direct property is ASKed.

No RDFS/OWL inference, redirect expansion, sitelink fallback, or schema
hierarchy traversal is applied.

Usage:
    python3.10 scripts/validate-dataset/check_gsc_counterfactual.py
        [--config scripts/validate-dataset/configs/gsc-validation-config.json]
        [--patterns rdfs7,rdfs5_7,...] [--sleep SECONDS]
        [--out-root data/validation/gsc]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
sys.path.insert(0, THIS_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts", "build-dataset"))

import gs_gsc_validator_common as common  # noqa: E402
import lod_query_helpers as lod  # noqa: E402
import rdfs_pattern_spec as pattern_spec  # noqa: E402
import validation_numeric as vnum  # noqa: E402
from shared._base import (  # noqa: E402
    RULE_CONFIGS,
    to_class_name,
    to_instance_name,
    to_property_name,
)

DEFAULT_CONFIG = os.path.join(THIS_DIR, "configs", "gsc-validation-config.json")
DEFAULT_OUT_ROOT = os.path.join(PROJECT_ROOT, "data", "validation", "gsc")

PATTERN_TRIPLE_KEYS = common.PATTERN_TRIPLE_KEYS
keytype = common.keytype
infer_role = common.infer_role
classify_triples = common.classify_triples
compatible_triple_indices = common.compatible_triple_indices
_source_lod_path = common.source_lod_path


def load_validation_config(config_path: str, patterns: list[str] | None) -> list[tuple[str, str, str]]:
    return common.load_validation_config(config_path, patterns, variant="gsc")


def _meta_from_path(rel_path: str) -> dict:
    return common.meta_from_path(rel_path, variant="gsc")


def _source_terms(pattern: str, source_entry: dict) -> dict[str, str]:
    return RULE_CONFIGS[pattern]["build_terms"](source_entry, ascii_fold=False)


def _render_for_dest_key(value: str, dest_key: str) -> str:
    """Render a raw shuffled value as GSC would render it in this destination.

    GSC case conversion is destination-slot based: if an instance lands in a
    property slot, it is rendered as a property name. The source recovery must
    therefore compare rendered values under the destination key's type, not the
    origin key's type.
    """
    t = keytype(dest_key)
    if t == "I":
        return to_instance_name(value, ascii_fold=False)
    if t == "P":
        return to_property_name(value, ascii_fold=False)
    if t == "C":
        return to_class_name(value, ascii_fold=False)
    raise ValueError(f"unknown destination key type for {dest_key}")


def _binding_candidates(
    *,
    pattern: str,
    dest_key: str,
    rendered_value: str,
    source_entry: dict,
) -> list[dict]:
    src_terms = _source_terms(pattern, source_entry)
    matches = []
    for origin_key, raw_value in src_terms.items():
        # GS/GSC are derangements: a source term cannot remain in its original
        # key. Enforcing this also disambiguates case-collapsed GSC renderings.
        if origin_key == dest_key:
            continue
        candidate = _render_for_dest_key(raw_value, dest_key)
        if candidate == rendered_value:
            uri = common.source_uri(pattern, origin_key, source_entry)
            hierarchy_uri = common.hierarchy_uri(origin_key, source_entry)
            matches.append({
                "dest_key": dest_key,
                "rendered": rendered_value,
                "source_rendered_for_dest": candidate,
                "raw_source_value": raw_value,
                "origin_key": origin_key,
                "origin_type": keytype(origin_key),
                "dest_type": keytype(dest_key),
                "uri": uri,
                "hierarchy_uri": hierarchy_uri,
                "source": "wikidata" if uri.startswith(common.WD_PREFIX) else "dbpedia",
            })
    return matches


def _candidate_assignments(candidate_map: dict[str, list[dict]]) -> list[dict[str, dict]]:
    dest_keys = list(candidate_map)
    out = []

    def rec(i: int, used_origin_keys: set[str], current: dict[str, dict]) -> None:
        if i == len(dest_keys):
            out.append(dict(current))
            return
        dest_key = dest_keys[i]
        for candidate in candidate_map[dest_key]:
            origin_key = candidate["origin_key"]
            if origin_key in used_origin_keys:
                continue
            current[dest_key] = candidate
            used_origin_keys.add(origin_key)
            rec(i + 1, used_origin_keys, current)
            used_origin_keys.remove(origin_key)
            current.pop(dest_key, None)

    rec(0, set(), {})
    return out


def _all_assignments_for_source(
    pattern: str,
    triples: list[tuple[str, str, str]],
    source_entry: dict,
) -> list[dict[str, dict]]:
    """All one-to-one deranged source assignments explaining the rendered terms.

    Empty if this source entry cannot explain the premise. No single assignment
    is selected: raw_unicode case conversion can collapse distinct source terms
    to the same rendered string, so several assignments may be equally
    consistent, and the caller must consider ALL of them (see
    collect_candidate_bindings for why).
    """
    dest_terms = common.extract_dest_terms(pattern, triples)
    candidate_map = {}
    for dest_key, rendered_value in dest_terms.items():
        candidates = _binding_candidates(
            pattern=pattern,
            dest_key=dest_key,
            rendered_value=rendered_value,
            source_entry=source_entry,
        )
        if not candidates:
            return []
        candidate_map[dest_key] = candidates
    return _candidate_assignments(candidate_map)


def collect_candidate_bindings(
    pattern: str,
    premise: str,
    source_entries: list[dict],
) -> tuple[list[tuple[str, str, str]], list[dict], str | None]:
    """All distinct candidate bindings consistent with a saved GSC premise.

    Ambiguity is deliberately NOT resolved to a single answer. At inference time
    the model sees only the rendered strings - no URIs and no resource types - so
    every string-consistent interpretation is a memorizable foothold. A GSC
    premise is therefore counterfactual only if EVERY interpretation is absent
    from LOD, and contaminated if ANY interpretation has a real triple. Selecting
    or excluding an ambiguous entry would under-count contamination; instead all
    interpretations are gathered and each type-compatible one is checked.

    Candidates are collected across every source entry and every in-entry
    assignment, then deduplicated by binding signature (identical URIs imply
    identical queries). This does not assume dataset index == source index.

    Returns (triples, candidates, error). Each candidate is
    {"source_index": int, "bindings": dict}. `error` is set only when no source
    entry explains the premise at all.
    """
    triples = pattern_spec.parse_triples(premise)
    if len(PATTERN_TRIPLE_KEYS[pattern]) != len(triples):
        raise ValueError(f"{pattern}: expected {len(PATTERN_TRIPLE_KEYS[pattern])} triples, got {len(triples)}")
    seen: set = set()
    candidates: list[dict] = []
    for source_index_0based, source_entry in enumerate(source_entries):
        for assignment in _all_assignments_for_source(pattern, triples, source_entry):
            sig = common.binding_signature(assignment)
            if sig in seen:
                continue
            seen.add(sig)
            candidates.append({"source_index": source_index_0based, "bindings": assignment})
    if not candidates:
        return triples, [], "no source entry explains saved GSC premise"
    return triples, candidates, None


def ask_triple(**kwargs):
    return common.ask_triple(variant_label="GSC", **kwargs)


def _entry_base(pattern: str, entry_index_0based: int, premise: str) -> dict:
    return {
        "pattern_id": pattern,
        "entry_index_0based": entry_index_0based,
        "entry_index_1based": entry_index_0based + 1,
        "premise": premise,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--patterns", default="", help="comma-separated subset of dataset patterns")
    args = ap.parse_args()

    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()] or None
    configured_files = load_validation_config(args.config, patterns)
    if not configured_files:
        raise SystemExit("no gsc dataset files configured")

    grand_total = 0
    plan = []
    for configured_pattern, rel_path, path in configured_files:
        data = json.load(open(path, encoding="utf-8"))
        meta = data["metadata"]
        pattern = meta["pattern_id"]
        if pattern != configured_pattern:
            raise SystemExit(f"{path}: config key {configured_pattern} does not match metadata pattern {pattern}")
        if pattern not in PATTERN_TRIPLE_KEYS:
            raise SystemExit(f"{pattern}: no PATTERN_TRIPLE_KEYS entry")
        lod_rel_path, lod_path = _source_lod_path(rel_path, meta)
        source_entries = json.load(open(lod_path, encoding="utf-8"))["entries"]
        entries = data["entries"]
        plan.append((pattern, rel_path, lod_rel_path, _meta_from_path(rel_path), entries, source_entries))
        grand_total += len(entries)

    done = 0
    overall = {
        "total": 0,
        "judged": 0,
        "structurally_counterfactual": 0,
        "lod_checked": 0,
        "explicitly_present": 0,
        "explicitly_absent": 0,
        "identity_unresolved": 0,
        "errors": 0,
    }

    for pattern, rel_path, lod_rel_path, meta, entries, source_entries in plan:
        structurally_counterfactual = lod_checked = explicitly_present = explicitly_absent = 0
        identity_unresolved = errors = 0
        structural_examples = []
        hit_examples = []
        explicitly_absent_examples = []
        identity_unresolved_examples = []
        error_examples = []

        for entry_index_0based, entry in enumerate(entries):
            done += 1
            remaining = grand_total - done
            premise = entry["premise_knowledge"]
            base = _entry_base(pattern, entry_index_0based, premise)

            try:
                triples, candidates, reason = collect_candidate_bindings(pattern, premise, source_entries)
                if not candidates:
                    raise ValueError(reason)
                roles = [infer_role(t) for t in triples]
                for cand in candidates:
                    ok, per = classify_triples(pattern, triples, cand["bindings"])
                    cand["compatible"] = ok
                    cand["per_triple"] = per
                    # A type-incompatible triple only rules out ITSELF, never its
                    # siblings, so a candidate is dismissed without any query only
                    # when EVERY one of its triples is type-incompatible.
                    cand["to_check"] = compatible_triple_indices(per)
            except Exception as exc:
                errors += 1
                error_examples.append({**base, "reason": str(exc), "stage": "structural_resolution"})
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> ERROR ({exc}) | remaining {remaining}")
                continue

            compatible_candidates = [c for c in candidates if c["to_check"]]
            source_indexes = sorted({c["source_index"] for c in candidates})

            if not compatible_candidates:
                # Every triple of every string-consistent interpretation is
                # type-incompatible: no triple can even take the shape of a real
                # fact, so the premise is counterfactual by construction.
                structurally_counterfactual += 1
                structural_examples.append({
                    **base,
                    "reason": "every triple of every candidate source assignment is type-incompatible; counterfactual by construction",
                    "candidate_count": len(candidates),
                    "source_entry_indexes_0based": source_indexes,
                    "candidates": [
                        {"source_index_0based": c["source_index"], "bindings": c["bindings"], "triples": c["per_triple"]}
                        for c in candidates
                    ],
                })
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> structural-counterfactual ({len(candidates)} cand) | remaining {remaining}")
                continue

            # Interpretations with at least one type-compatible triple exist. The
            # premise is contaminated if ANY such triple of ANY interpretation is
            # explicitly present; it is counterfactual only if every checked triple
            # of every interpretation is absent.
            found_present = None
            any_identity_unresolved = False
            any_error = False
            per_candidate_checks = []
            for cand in compatible_candidates:
                bindings = cand["bindings"]
                checks = []
                cand_present = None
                for triple_index in cand["to_check"]:
                    check = ask_triple(
                        pattern=pattern,
                        entry_index_0based=entry_index_0based,
                        role=roles[triple_index],
                        triple=triples[triple_index],
                        slot_keys=PATTERN_TRIPLE_KEYS[pattern][triple_index],
                        bindings=bindings,
                    )
                    checks.append(check)
                    time.sleep(args.sleep)
                    # An unresolved identity only means THIS triple could not be
                    # decided; a sibling triple may still be explicitly present,
                    # and a present triple outranks an unresolved one.
                    if check.get("identity_unresolved"):
                        any_identity_unresolved = True
                        continue
                    if check["explicitly_present"] is None:
                        any_error = True
                        continue
                    if check["explicitly_present"]:
                        cand_present = check
                        break
                per_candidate_checks.append({
                    "source_index_0based": cand["source_index"],
                    "bindings": bindings,
                    "triple_checks": checks,
                })
                if cand_present is not None:
                    found_present = {
                        "source_index_0based": cand["source_index"],
                        "bindings": bindings,
                        "triple": cand_present,
                    }
                    break

            if found_present is not None:
                lod_checked += 1
                explicitly_present += 1
                hit_examples.append({
                    **base,
                    "reason": "at least one type-compatible interpretation has a triple explicitly present in LOD",
                    "candidate_count": len(candidates),
                    "compatible_candidate_count": len(compatible_candidates),
                    "source_entry_indexes_0based": source_indexes,
                    "present": found_present,
                    "candidate_checks": per_candidate_checks,
                })
                verdict = "CONTAMINATED"
            elif any_identity_unresolved:
                identity_unresolved += 1
                identity_unresolved_examples.append({
                    **base,
                    "reason": "a type-compatible interpretation could not be ruled out because its owl:sameAs identity was unresolved",
                    "source_entry_indexes_0based": source_indexes,
                    "candidate_checks": per_candidate_checks,
                })
                verdict = "IDENTITY-UNRESOLVED"
            elif any_error:
                errors += 1
                error_examples.append({
                    **base,
                    "reason": "SPARQL query failed after retries for a type-compatible interpretation",
                    "stage": "direct_ask",
                    "source_entry_indexes_0based": source_indexes,
                    "candidate_checks": per_candidate_checks,
                })
                verdict = "ERROR"
            else:
                lod_checked += 1
                explicitly_absent += 1
                explicitly_absent_examples.append({
                    **base,
                    "reason": "every type-compatible interpretation had all triples absent from LOD",
                    "compatible_candidate_count": len(compatible_candidates),
                    "source_entry_indexes_0based": source_indexes,
                    "candidate_checks": per_candidate_checks,
                })
                verdict = "counterfactual"

            lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> {verdict} | remaining {remaining}")
            time.sleep(args.sleep)

        counterfactual = structurally_counterfactual + explicitly_absent
        judged = structurally_counterfactual + lod_checked
        out = {
            "metadata": {
                "validation_type": "gsc_premise_explicit_lod_presence",
                "variant": "gsc",
                "granularity": "premise",
                "source_dataset": rel_path,
                "source_lod_sample": lod_rel_path,
                "validation_config": os.path.relpath(args.config, PROJECT_ROOT),
                "pattern_id": pattern,
                "pattern_spec": pattern_spec.PATTERN_SPEC[pattern],
                "pattern_triple_keys": PATTERN_TRIPLE_KEYS[pattern],
                "source_matching_policy": (
                    "Each saved GSC premise is matched to every lod-sample entry and "
                    "one-to-one term assignment that can explain its raw_unicode "
                    "case-converted surface terms. The validator does not assume "
                    "dataset entry index equals source entry index, and ambiguous "
                    "surface interpretations are all checked."
                ),
                "fetch_uid": meta["fetch_uid"],
                "build_uid": meta["build_uid"],
                "n": meta["n"],
                "lod_policy": (
                    "LOD explicit presence is ground truth. Type-incompatible triples are "
                    "absent by construction; every type-compatible triple is checked by direct "
                    "ASK, and an entry is counterfactual only if all checked triples of all "
                    "candidate interpretations are absent. Each graph is asked with its own "
                    "vocabulary: RDFS/RDF predicates on DBpedia, P1647/P279/P31 on Wikidata. "
                    "No RDFS/OWL inference, transitive hierarchy traversal, redirect expansion, "
                    "or sitelink fallback is used."
                ),
                "identity_policy": lod.IDENTITY_POLICY,
                "logging_policy": (
                    "Every emitted example stores entry index, premise, recovered candidate "
                    "term-to-URI bindings, and either structural mismatch details or "
                    "per-triple direct ASK logs."
                ),
                "dbpedia_endpoint": lod.DBP_ENDPOINT,
                "wikidata_endpoint": lod.WD_ENDPOINT,
                "query_retry_policy": {
                    "timeout_seconds": lod.SPARQL_TIMEOUT_SECONDS,
                    "dbpedia_server_timeout_ms": lod.SPARQL_TIMEOUT_SECONDS * 1000,
                    "wikidata_server_timeout_ms": None,
                    "wikidata_timeout_policy": (
                        "Wikidata/Blazegraph receives only the client-side HTTP timeout; "
                        "the Virtuoso server-side timeout parameter is sent only to DBpedia"
                    ),
                    "max_retries": lod.SPARQL_RETRIES,
                    "backoff_seconds": lod.SPARQL_BACKOFF_SECONDS,
                    "backoff": "exponential",
                },
                "result_schema": (
                    "judged is the counterfactual-rate denominator. For GSC, "
                    "judged == structurally_counterfactual + lod_checked; "
                    "identity_unresolved and errors are excluded. Counts are canonical; "
                    "counterfactual_rate_fraction and counterfactual_rate_decimal are "
                    "derived from the integer counts. No binary-float rate is serialized."
                ),
                "validated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "result": {
                "total": len(entries),
                "judged": judged,
                "structurally_counterfactual": structurally_counterfactual,
                "lod_checked": lod_checked,
                "explicitly_present": explicitly_present,
                "explicitly_absent": explicitly_absent,
                "identity_unresolved": identity_unresolved,
                "errors": errors,
                "contaminated": explicitly_present,
                "counterfactual": counterfactual,
                "counterfactual_rate_fraction": vnum.rate_fraction_str(counterfactual, judged),
                "counterfactual_rate_decimal": vnum.rate_decimal_str(counterfactual, judged),
                "structurally_counterfactual_examples": structural_examples,
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
        rate = f"{counterfactual}/{judged}={counterfactual/judged:.1%}" if judged else "n/a"
        lod._log(
            f"  -> {pattern}: counterfactual {rate} "
            f"(structural={structurally_counterfactual}, lod_checked={lod_checked}, "
            f"present={explicitly_present}, identity_unresolved={identity_unresolved}, errors={errors}) "
            f"written {out_path}"
        )

        overall["total"] += len(entries)
        overall["judged"] += judged
        overall["structurally_counterfactual"] += structurally_counterfactual
        overall["lod_checked"] += lod_checked
        overall["explicitly_present"] += explicitly_present
        overall["explicitly_absent"] += explicitly_absent
        overall["identity_unresolved"] += identity_unresolved
        overall["errors"] += errors

    overall["counterfactual"] = overall["structurally_counterfactual"] + overall["explicitly_absent"]
    judged = overall["judged"]
    lod._log("\n=== overall ===")
    lod._log(
        f"total={overall['total']} judged={judged} "
        f"structurally_counterfactual={overall['structurally_counterfactual']} "
        f"lod_checked={overall['lod_checked']} explicitly_present={overall['explicitly_present']} "
        f"explicitly_absent={overall['explicitly_absent']} "
        f"identity_unresolved={overall['identity_unresolved']} errors={overall['errors']}"
    )
    if judged:
        lod._log(f"counterfactual rate: {overall['counterfactual']}/{judged} = {overall['counterfactual']/judged:.1%}")


if __name__ == "__main__":
    main()
