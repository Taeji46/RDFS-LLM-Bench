"""Validate GS premises for explicit LOD contamination.

Scope: this script validates only GS (Global Shuffle). GSC has its own
validator because GSC must enumerate all raw_unicode case-converted surface
interpretations.

GS first receives a per-triple structural check: a term appearing in a position
whose resource type is impossible for that position makes THAT triple absent by
construction, so it needs no query. A type-incompatible triple never licenses a
verdict on its siblings, and an entry counts as counterfactual only once every
remaining triple has been asked and found absent.

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
    python3.10 scripts/validate-dataset/check_gs_counterfactual.py
        [--config scripts/validate-dataset/configs/gs-validation-config.json]
        [--patterns rdfs7,rdfs5_7,...] [--sleep SECONDS]
        [--out-root data/validation/gs]
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
)

DEFAULT_CONFIG = os.path.join(THIS_DIR, "configs", "gs-validation-config.json")
DEFAULT_OUT_ROOT = os.path.join(PROJECT_ROOT, "data", "validation", "gs")

PATTERN_TRIPLE_KEYS = common.PATTERN_TRIPLE_KEYS
keytype = common.keytype
infer_role = common.infer_role
classify_triples = common.classify_triples
compatible_triple_indices = common.compatible_triple_indices
_source_lod_path = common.source_lod_path


def load_validation_config(config_path: str, patterns: list[str] | None) -> list[tuple[str, str, str]]:
    return common.load_validation_config(config_path, patterns, variant="gs")


def _meta_from_path(rel_path: str) -> dict:
    return common.meta_from_path(rel_path, variant="gs")


def _source_terms(pattern: str, source_entry: dict) -> dict[str, str]:
    return RULE_CONFIGS[pattern]["build_terms"](source_entry, ascii_fold=False)


def _resolve_binding(
    *,
    pattern: str,
    dest_key: str,
    rendered_value: str,
    source_entry: dict,
) -> tuple[dict | None, str | None]:
    src_terms = _source_terms(pattern, source_entry)
    matches = []
    for origin_key, raw_value in src_terms.items():
        if raw_value == rendered_value:
            uri = common.source_uri(pattern, origin_key, source_entry)
            hierarchy_uri = common.hierarchy_uri(origin_key, source_entry)
            matches.append({
                "dest_key": dest_key,
                "rendered": rendered_value,
                "origin_key": origin_key,
                "origin_type": keytype(origin_key),
                "dest_type": keytype(dest_key),
                "uri": uri,
                "hierarchy_uri": hierarchy_uri,
                "source": "wikidata" if uri.startswith(common.WD_PREFIX) else "dbpedia",
            })
    if not matches:
        return None, f"no source term matches rendered value {rendered_value!r} for destination key {dest_key}"
    unique = {(m["origin_key"], m["origin_type"], m["uri"]) for m in matches}
    if len(unique) > 1:
        return None, f"ambiguous source term for {dest_key}={rendered_value!r}: {matches}"
    return matches[0], None


def resolve_entry_bindings(
    pattern: str,
    premise: str,
    source_entry: dict,
) -> tuple[dict[str, dict] | None, list[tuple[str, str, str]] | None, str | None]:
    triples = pattern_spec.parse_triples(premise)
    if len(PATTERN_TRIPLE_KEYS[pattern]) != len(triples):
        raise ValueError(f"{pattern}: expected {len(PATTERN_TRIPLE_KEYS[pattern])} triples, got {len(triples)}")
    dest_terms = common.extract_dest_terms(pattern, triples)
    bindings = {}
    for dest_key, rendered_value in dest_terms.items():
        binding, reason = _resolve_binding(
            pattern=pattern,
            dest_key=dest_key,
            rendered_value=rendered_value,
            source_entry=source_entry,
        )
        if binding is None:
            return None, triples, reason
        bindings[dest_key] = binding
    return bindings, triples, None


def resolve_entry_bindings_from_sources(
    pattern: str,
    premise: str,
    source_entries: list[dict],
) -> tuple[dict[str, dict] | None, list[tuple[str, str, str]] | None, int | None, str | None]:
    """Find the unique source entry that explains a saved GS premise.

    This deliberately does not rely on dataset entry index matching the
    lod-sample index, because GS generation may skip non-derangeable source
    entries. If source matching is not unique, validation fails loudly instead
    of silently binding the premise to the wrong source row.

    This is intentionally O(dataset_entries * source_entries). GS validation is
    network-bound only for the small structurally compatible subset; the local
    exhaustive source recovery is kept explicit so future dataset regeneration
    cannot silently reintroduce an index-alignment assumption.
    """
    candidates = []
    first_error = None
    for source_index_0based, source_entry in enumerate(source_entries):
        bindings, triples, reason = resolve_entry_bindings(pattern, premise, source_entry)
        if bindings is not None and triples is not None:
            candidates.append((source_index_0based, bindings, triples))
        elif first_error is None:
            first_error = reason
    if not candidates:
        return None, None, None, f"no source entry explains saved GS premise; first mismatch: {first_error}"
    if len(candidates) > 1:
        indexes = [c[0] for c in candidates[:20]]
        return None, None, None, f"ambiguous source entries for saved GS premise: {indexes}"
    source_index_0based, bindings, triples = candidates[0]
    return bindings, triples, source_index_0based, None


def ask_triple(**kwargs):
    return common.ask_triple(variant_label="GS", **kwargs)


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
        raise SystemExit("no gs dataset files configured")

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
                bindings, triples, source_index_0based, reason = resolve_entry_bindings_from_sources(
                    pattern,
                    premise,
                    source_entries,
                )
                if bindings is None or triples is None or source_index_0based is None:
                    raise ValueError(reason)
                compatible, per_triple = classify_triples(pattern, triples, bindings)
            except Exception as exc:
                errors += 1
                error_examples.append({**base, "reason": str(exc), "stage": "structural_resolution"})
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> ERROR ({exc}) | remaining {remaining}")
                continue

            # A type-incompatible triple only proves ITS OWN absence. The entry is
            # counterfactual by construction only when EVERY premise triple is
            # type-incompatible; otherwise each remaining type-compatible triple
            # must still be asked, because one of them may be a real LOD fact that
            # survived the shuffle.
            to_check = compatible_triple_indices(per_triple)
            if not to_check:
                structurally_counterfactual += 1
                structural_examples.append({
                    **base,
                    "reason": "every premise triple has a term whose original resource type is incompatible with its rendered position",
                    "source_entry_index_0based": source_index_0based,
                    "source_entry_index_1based": source_index_0based + 1,
                    "bindings": bindings,
                    "triples": per_triple,
                })
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> structural-counterfactual | remaining {remaining}")
                continue

            triple_checks = []
            entry_identity_unresolved = False
            entry_error = False
            roles_all = [infer_role(triple) for triple in triples]
            slots_all = PATTERN_TRIPLE_KEYS[pattern]
            for triple_index in to_check:
                check = ask_triple(
                    pattern=pattern,
                    entry_index_0based=entry_index_0based,
                    role=roles_all[triple_index],
                    triple=triples[triple_index],
                    slot_keys=slots_all[triple_index],
                    bindings=bindings,
                )
                triple_checks.append(check)
                time.sleep(args.sleep)
                # An unresolved identity only means THIS triple could not be
                # decided; a sibling triple may still be explicitly present, and
                # a present triple outranks an unresolved one. Keep checking.
                if check.get("identity_unresolved"):
                    entry_identity_unresolved = True
                    continue
                if check["explicitly_present"] is None:
                    entry_error = True

            present_checks = [c for c in triple_checks if c["explicitly_present"]]
            if present_checks:
                lod_checked += 1
                explicitly_present += 1
                hit_examples.append({
                    **base,
                    "reason": "at least one type-compatible premise triple is explicitly present in LOD",
                    "source_entry_index_0based": source_index_0based,
                    "source_entry_index_1based": source_index_0based + 1,
                    "bindings": bindings,
                    "triple_checks": triple_checks,
                    "real_triples": present_checks,
                    "nonblocking_query_errors": [c for c in triple_checks if c["explicitly_present"] is None],
                })
                verdict = "CONTAMINATED"
            elif entry_identity_unresolved:
                identity_unresolved += 1
                identity_unresolved_examples.append({
                    **base,
                    "reason": "Wikidata property instance triple could not be checked because explicit owl:sameAs identity was unresolved",
                    "source_entry_index_0based": source_index_0based,
                    "source_entry_index_1based": source_index_0based + 1,
                    "bindings": bindings,
                    "triple_checks": triple_checks,
                })
                verdict = "IDENTITY-UNRESOLVED"
            elif entry_error:
                errors += 1
                error_examples.append({
                    **base,
                    "reason": "SPARQL query failed after retries",
                    "stage": "direct_ask",
                    "source_entry_index_0based": source_index_0based,
                    "source_entry_index_1based": source_index_0based + 1,
                    "bindings": bindings,
                    "triple_checks": triple_checks,
                })
                verdict = "ERROR"
            else:
                lod_checked += 1
                explicitly_absent += 1
                explicitly_absent_examples.append({
                    **base,
                    "reason": "all type-compatible premise triples returned direct ASK false",
                    "source_entry_index_0based": source_index_0based,
                    "source_entry_index_1based": source_index_0based + 1,
                    "bindings": bindings,
                    "triple_checks": triple_checks,
                })
                verdict = "counterfactual"

            lod._log(f"[ {done}/{grand_total} ] {pattern:12} -> {verdict} | remaining {remaining}")
            time.sleep(args.sleep)

        counterfactual = structurally_counterfactual + explicitly_absent
        judged = structurally_counterfactual + lod_checked
        out = {
            "metadata": {
                "validation_type": "gs_premise_explicit_lod_presence",
                "variant": "gs",
                "granularity": "premise",
                "source_dataset": rel_path,
                "source_lod_sample": lod_rel_path,
                "validation_config": os.path.relpath(args.config, PROJECT_ROOT),
                "pattern_id": pattern,
                "pattern_spec": pattern_spec.PATTERN_SPEC[pattern],
                "pattern_triple_keys": PATTERN_TRIPLE_KEYS[pattern],
                "source_matching_policy": (
                    "Each saved GS premise is matched to the unique lod-sample entry "
                    "that explains all rendered terms. The validator does not assume "
                    "dataset entry index equals source entry index."
                ),
                "fetch_uid": meta["fetch_uid"],
                "build_uid": meta["build_uid"],
                "n": meta["n"],
                "lod_policy": (
                    "LOD explicit presence is ground truth. Type-incompatible triples are "
                    "absent by construction; every type-compatible triple is checked by direct "
                    "ASK, and an entry is counterfactual only if all checked triples are absent. "
                    "Each graph is asked with its own vocabulary: RDFS/RDF predicates on "
                    "DBpedia, P1647/P279/P31 on Wikidata. No RDFS/OWL inference, transitive "
                    "hierarchy traversal, redirect expansion, or sitelink fallback is used."
                ),
                "identity_policy": lod.IDENTITY_POLICY,
                "logging_policy": (
                    "Every emitted example stores entry index, premise, recovered term-to-URI "
                    "bindings, and either structural mismatch details or per-triple direct ASK logs."
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
                    "judged is the counterfactual-rate denominator. For GS, "
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
