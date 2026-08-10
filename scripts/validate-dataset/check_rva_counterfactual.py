"""Validate that RVA (Random Vocabulary Assignment) premises are counterfactual.

RVA assigns randomly sampled DBpedia local names (resources / properties /
classes) to the term slots of each inference pattern. A *premise* is
"counterfactual" only when NONE of its triples hold in the source KG (DBpedia).
Even a single real triple gives a model a memorized foothold, so a premise is
"contaminated" if ANY one of its triples is a real fact.

Granularity is the PREMISE (= one dataset entry). For each premise we emit a
SINGLE disjunctive ASK over its triples ( ASK { {t1} UNION {t2} UNION ... } ):
it returns true iff AT LEAST ONE triple holds in DBpedia. The premise is
clean-counterfactual iff this returns false. So the primary pass is
#queries == #entries (e.g. 100 per pattern). For each contaminated premise
(union = true) we then run one ASK per triple to identify which triple(s) are
real (the culprit); this follow-up runs only on contaminated premises, so it is
near-free when contamination is rare.

Each triple's conjunct is built per rule (hardcoded structure per pattern; see
PATTERN_SPEC), so each pattern's premise shape is declared explicitly and a
mismatch fails loudly rather than silently issuing a wrong query.

Triple role -> ASK conjunct (namespaces):
  domain        <i, rdfs:domain, X>        dbo:i  rdfs:domain  dbo:X
  range         <i, rdfs:range,  Y>        dbo:i  rdfs:range   dbo:Y
  subClassOf    <X, rdfs:subClassOf, Y>    dbo:X  rdfs:subClassOf  dbo:Y
  subPropertyOf <i, rdfs:subPropertyOf, j> (dbo|dbp):i rdfs:subPropertyOf (dbo|dbp):j
  type          <a, rdf:type, X>           dbr:a  rdf:type     dbo:X
  instance      <a, i, b>                  dbr:a (dbo|dbp):i   dbr:b

Always validates every entry of every pattern (this is a validation artifact,
not a sample). One output file is written per inference pattern, mirroring the
source `{n}-rule/` layout, with the source dataset id encoded in the name
(`dataset__...` -> `validation__...`).

Usage:
    python scripts/validate-dataset/check_rva_counterfactual.py
        [--config scripts/validate-dataset/configs/rva-validation-config.json]
        [--patterns rdfs2,rdfs7,...] [--sleep SECONDS]
        [--out-root data/validation/rva]

Writes (one per pattern):
    data/validation/rva/{n}-rule/validation__rva__{pattern}__n{N}__{build_uid}.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import time
import urllib.parse

import lod_query_helpers as lod
import rdfs_pattern_spec as pattern_spec
import validation_numeric as vnum

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(THIS_DIR))
DEFAULT_CONFIG = os.path.join(THIS_DIR, "configs", "rva-validation-config.json")
DEFAULT_OUT_ROOT = os.path.join(PROJECT_ROOT, "data", "validation", "rva")

DBP_ENDPOINT = lod.DBP_ENDPOINT
RES = lod.RES
DBO = lod.DBO
DBP = lod.DBP
RDFS = lod.RDFS
RDF = lod.RDF

SPARQL_TIMEOUT_SECONDS = lod.SPARQL_TIMEOUT_SECONDS
SPARQL_RETRIES = lod.SPARQL_RETRIES
SPARQL_BACKOFF_SECONDS = lod.SPARQL_BACKOFF_SECONDS
# Re-ask a false premise UNION before accepting it as counterfactual.
#
# Only this query needs it. The premise UNION is by far the heaviest ASK any
# validator issues (one UNION branch per premise triple, several of them with an
# unbound predicate variable plus a FILTER over the dbo/dbp namespace pair), so
# it is the one most exposed to Virtuoso returning an early, incomplete answer.
# A false here is also the counterfactual verdict itself, so a spurious false
# would silently inflate the counterfactual rate.
#
# The single-triple ASKs used elsewhere (RVA culprit follow-ups, and every LS/GS
# check) bind subject, predicate and object, making them plain index lookups
# that do not hit anytime-query limits, so they are accepted on first read.
# A true is never re-asked in any case: it is positive evidence and cannot be
# produced by an incomplete result.
UNION_ASK_FALSE_CONFIRM_ATTEMPTS = 2


def _enc(local: str) -> str:
    return urllib.parse.quote(local, safe="_()-,.'!*")


def parse_triples(premise: str) -> list[tuple[str, str, str]]:
    return pattern_spec.parse_triples(premise)


# --- per-role conjunct builders (i = unique index to avoid variable clashes) ---

def _c_domain(i, s, o):
    return f"<{DBO}{_enc(s)}> <{RDFS}domain> <{DBO}{_enc(o)}> ."


def _c_range(i, s, o):
    return f"<{DBO}{_enc(s)}> <{RDFS}range> <{DBO}{_enc(o)}> ."


def _c_subclass(i, s, o):
    return f"<{DBO}{_enc(s)}> <{RDFS}subClassOf> <{DBO}{_enc(o)}> ."


def _c_subprop(i, s, o):
    return (
        f"?sp{i}a <{RDFS}subPropertyOf> ?sp{i}b . "
        f"FILTER(?sp{i}a IN (<{DBO}{_enc(s)}>,<{DBP}{_enc(s)}>)) "
        f"FILTER(?sp{i}b IN (<{DBO}{_enc(o)}>,<{DBP}{_enc(o)}>))"
    )


def _c_type(i, s, o):
    return f"<{RES}{_enc(s)}> <{RDF}type> <{DBO}{_enc(o)}> ."


def _c_instance(i, s, p, o):
    return (
        f"<{RES}{_enc(s)}> ?ip{i} <{RES}{_enc(o)}> . "
        f"FILTER(?ip{i} IN (<{DBO}{_enc(p)}>,<{DBP}{_enc(p)}>))"
    )


# Expected predicate per role (used to validate the premise matches the spec).
_ROLE_PRED = pattern_spec.ROLE_PRED
PATTERN_SPEC = pattern_spec.PATTERN_SPEC


def build_conjuncts(
    pattern: str, triples: list[tuple[str, str, str]]
) -> list[tuple[str, tuple[str, str, str], str]]:
    """Return one (role, triple, SPARQL-conjunct) per triple of `pattern`.

    Raises ValueError if the parsed premise does not match the hardcoded
    PATTERN_SPEC (wrong arity or unexpected predicate), so a structural drift in
    the data surfaces loudly instead of producing a silently-wrong query.
    """
    roles = PATTERN_SPEC[pattern]
    if len(roles) != len(triples):
        raise ValueError(
            f"{pattern}: expected {len(roles)} triples {roles}, got {len(triples)}: {triples}"
        )
    out = []
    for i, (role, (s, p, o)) in enumerate(zip(roles, triples)):
        if role == "instance":
            if p in _ROLE_PRED.values():
                raise ValueError(f"{pattern}#{i}: expected instance predicate, got '{p}'")
            conjunct = _c_instance(i, s, p, o)
        else:
            if p != _ROLE_PRED[role]:
                raise ValueError(f"{pattern}#{i}: expected predicate '{_ROLE_PRED[role]}', got '{p}'")
            conjunct = {
                "domain": _c_domain,
                "range": _c_range,
                "subClassOf": _c_subclass,
                "subPropertyOf": _c_subprop,
                "type": _c_type,
            }[role](i, s, o)
        out.append((role, (s, p, o), conjunct))
    return out


def union_ask(conjuncts: list[tuple[str, tuple[str, str, str], str]]) -> str:
    """ONE disjunctive ASK over all triples: true iff ANY triple holds."""
    return "ASK { " + " UNION ".join(f"{{ {c} }}" for (_, _, c) in conjuncts) + " }"


def single_ask(conjunct: str) -> str:
    """ASK for a single triple (used to find the culprit in a contaminated premise)."""
    return "ASK { " + conjunct + " }"


PARTIAL_RESULT_HEADER_NAMES = lod.PARTIAL_RESULT_HEADER_NAMES


def ask_logged(
    query: str,
    timeout: int = SPARQL_TIMEOUT_SECONDS,
    retries: int = SPARQL_RETRIES,
    backoff: float = SPARQL_BACKOFF_SECONDS,
    label: str = "ASK",
    confirm_false_attempts: int = 1,
):
    """Return (True|False, None, query_log) or (None, reason, query_log).

    The public DBpedia endpoint is flaky (transient 502/503/timeout). We retry
    with exponential backoff so a momentary outage does not turn a valid premise
    into a permanent ERROR that would pollute the counterfactual rate.
    """
    return lod.ask_endpoint(
        DBP_ENDPOINT,
        query,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        label=label,
        confirm_false_attempts=confirm_false_attempts,
    )


def ask(
    query: str,
    timeout: int = SPARQL_TIMEOUT_SECONDS,
    retries: int = SPARQL_RETRIES,
    backoff: float = SPARQL_BACKOFF_SECONDS,
):
    """Backward-compatible two-value ASK helper for older validation scripts."""
    value, reason, _query_log = ask_logged(query, timeout=timeout, retries=retries, backoff=backoff)
    return value, reason


def _meta_from_path(rel_path: str) -> dict:
    """Extract n-rule dir, n, build_uid, output filename from a dataset path."""
    fname = os.path.basename(rel_path)                       # dataset__rva__rdfs2__n100__b-xxxx.json
    n_rule_dir = os.path.basename(os.path.dirname(rel_path))  # 1-rule
    n = re.search(r"__n(\d+)__", fname)
    uid = re.search(r"__(b-[0-9a-f]+)\.json$", fname)
    out_name = fname.replace("dataset__", "validation__", 1)
    return {
        "n_rule_dir": n_rule_dir,
        "n": int(n.group(1)) if n else None,
        "build_uid": uid.group(1) if uid else None,
        "out_name": out_name,
    }


def _short(premise: str, width: int = 60) -> str:
    p = " ".join(premise.split())
    return p if len(p) <= width else p[: width - 1] + "…"


def _triple_text(triple: tuple[str, str, str]) -> str:
    return pattern_spec.triple_text(triple)


def _entry_log_base(pattern: str, entry_index_0based: int, premise: str) -> dict:
    return {
        "pattern_id": pattern,
        "entry_index_0based": entry_index_0based,
        "entry_index_1based": entry_index_0based + 1,
        "premise": premise,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--patterns", default="",
                    help="comma-separated subset of patterns in the config (for parallel splitting)")
    args = ap.parse_args()

    config = json.load(open(args.config, encoding="utf-8"))
    if args.patterns:
        patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
        unknown = [p for p in patterns if p not in config]
        if unknown:
            raise SystemExit(f"unknown patterns {unknown}; valid: {list(config)}")
        config = {p: config[p] for p in patterns}

    # First pass: load every premise per pattern to know the global total
    # (for "remaining"). One premise == one conjunctive ASK.
    plan = []   # (pattern, rel_path, meta, [ (entry_idx, premise_str, [triples]), ... ])
    for pattern, rel_path in config.items():
        path = os.path.join(PROJECT_ROOT, rel_path)
        entries = json.load(open(path, encoding="utf-8"))["entries"]
        premises = [
            (entry_index_0based, e["premise_knowledge"], parse_triples(e["premise_knowledge"]))
            for entry_index_0based, e in enumerate(entries)
        ]
        plan.append((pattern, rel_path, _meta_from_path(rel_path), premises))

    grand_total = sum(len(p) for _, _, _, p in plan)   # == number of premises
    done = 0
    overall = {"judged": 0, "lod_checked": 0, "explicitly_present": 0, "explicitly_absent": 0, "errors": 0}

    for pattern, rel_path, meta, premises in plan:
        lod_checked = explicitly_present = explicitly_absent = errors = 0
        hit_examples = []
        explicitly_absent_examples = []
        error_examples = []
        for entry_index_0based, premise_str, triples in premises:
            done += 1
            remaining = grand_total - done
            base = _entry_log_base(pattern, entry_index_0based, premise_str)
            try:
                conjuncts = build_conjuncts(pattern, triples)
            except ValueError as e:
                errors += 1
                error_examples.append({
                    **base,
                    "reason": str(e),
                    "query": None,
                    "query_log": None,
                })
                lod._log(f"[ {done}/{grand_total} ] {pattern:12} {_short(premise_str)} -> ERROR (spec: {e}) | remaining {remaining}")
                continue
            uq = union_ask(conjuncts)
            r, reason, union_log = ask_logged(
                uq,
                label=f"premise UNION entry {entry_index_0based + 1}",
                confirm_false_attempts=UNION_ASK_FALSE_CONFIRM_ATTEMPTS,
            )
            if r is None:
                errors += 1
                verdict = f"ERROR ({reason})"
                error_examples.append({
                    **base,
                    "reason": reason,
                    "query": uq,
                    "query_log": union_log,
                })
            elif r:
                # At least one triple holds in DBpedia -> contaminated (NOT a
                # clean counterfactual). Run one ASK per triple to find which.
                lod_checked += 1
                explicitly_present += 1
                real_triples = []
                triple_checks = []
                for role, (s, p, o), c in conjuncts:
                    sq = single_ask(c)
                    sr, sreason, single_log = ask_logged(
                        sq,
                        label=f"culprit {pattern} entry {entry_index_0based + 1} {role}",
                    )
                    triple_check = {
                        "role": role,
                        "triple": f"<{s}, {p}, {o}>",
                        "explicitly_present": bool(sr) if sr is not None else None,
                        "reason": sreason,
                        "query": sq,
                        "query_log": single_log,
                    }
                    triple_checks.append(triple_check)
                    if sr:
                        real_triples.append({
                            "triple": f"<{s}, {p}, {o}>",
                            "role": role,
                            "query": sq,
                            "query_log": single_log,
                        })
                    time.sleep(args.sleep)
                verdict = f"REAL-TRIPLE ({len(real_triples)}/{len(conjuncts)})"
                hit_examples.append({
                    **base,
                    "reason": "DBpedia disjunctive UNION ASK true",
                    "union_query": uq,
                    "union_query_log": union_log,
                    "triples": [
                        {"role": role, "triple": _triple_text(triple)}
                        for role, triple, _conjunct in conjuncts
                    ],
                    "triple_checks": triple_checks,
                    "real_triples": real_triples,
                })
            else:
                lod_checked += 1
                explicitly_absent += 1
                verdict = "counterfactual"
                explicitly_absent_examples.append({
                    **base,
                    "reason": "DBpedia disjunctive UNION ASK false",
                    "union_query": uq,
                    "union_query_log": union_log,
                    "triples": [
                        {"role": role, "triple": _triple_text(triple)}
                        for role, triple, _conjunct in conjuncts
                    ],
                })
            lod._log(f"[ {done}/{grand_total} ] {pattern:12} {_short(premise_str)} -> {verdict} | remaining {remaining}")
            time.sleep(args.sleep)

        cf = explicitly_absent
        judged = lod_checked
        out = {
            "metadata": {
                "validation_type": "rva_premise_explicit_lod_presence",
                "granularity": "premise",
                "match_logic": (
                    "direct DBpedia ASK only; any-triple disjunctive UNION; "
                    "counterfactual iff no premise triple is explicitly present"
                ),
                "lod_policy": (
                    "LOD explicit presence is ground truth. No RDFS/OWL inference, "
                    "no transitive subPropertyOf/subClassOf, no redirect expansion, "
                    "and no identity fallback is applied."
                ),
                "source_dataset": rel_path,
                "validation_config": os.path.relpath(args.config, PROJECT_ROOT),
                "pattern_id": pattern,
                "premise_spec": PATTERN_SPEC[pattern],
                "build_uid": meta["build_uid"],
                "n": meta["n"],
                "endpoint": DBP_ENDPOINT,
                "logging_policy": (
                    "Every emitted example stores entry index, premise, SPARQL query, "
                    "selected SPARQL response headers, and per-attempt query log. "
                    "Contaminated premises additionally "
                    "store per-triple culprit ASK logs."
                ),
                "query_retry_policy": {
                    "timeout_seconds": SPARQL_TIMEOUT_SECONDS,
                    "server_timeout_ms": SPARQL_TIMEOUT_SECONDS * 1000,
                    "max_retries": SPARQL_RETRIES,
                    "backoff_seconds": SPARQL_BACKOFF_SECONDS,
                    "backoff": "exponential",
                    "partial_result_headers": list(PARTIAL_RESULT_HEADER_NAMES),
                    "partial_result_handling": (
                        "responses with Virtuoso/DBpedia partial-result headers "
                        "are retried and are not accepted as evidence of absence"
                    ),
                    "union_ask_false_confirm_attempts": UNION_ASK_FALSE_CONFIRM_ATTEMPTS,
                },
                "result_schema": (
                    "judged is the counterfactual-rate denominator. For RVA, "
                    "judged == lod_checked == explicitly_present + explicitly_absent; "
                    "errors are excluded. Counts are canonical; counterfactual_rate_fraction "
                    "and counterfactual_rate_decimal are derived from the integer counts. "
                    "No binary-float rate is serialized."
                ),
                "validated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "result": {
                "total": len(premises),
                "judged": judged,
                "lod_checked": lod_checked,
                "explicitly_present": explicitly_present,
                "explicitly_absent": explicitly_absent,
                "contaminated": explicitly_present,
                "errors": errors,
                "counterfactual": cf,
                "counterfactual_rate_fraction": vnum.rate_fraction_str(cf, judged),
                "counterfactual_rate_decimal": vnum.rate_decimal_str(cf, judged),
                "hit_examples": hit_examples,
                "explicitly_absent_examples": explicitly_absent_examples,
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
            f"  -> {pattern}: counterfactual {rate} "
            f"(explicitly_present={explicitly_present}, errors={errors}) written {out_path}"
        )

        overall["judged"] += judged
        overall["lod_checked"] += lod_checked
        overall["explicitly_present"] += explicitly_present
        overall["explicitly_absent"] += explicitly_absent
        overall["errors"] += errors

    lod._log("\n=== overall ===")
    judged = overall["judged"]
    cf = overall["explicitly_absent"]
    lod._log(
        f"judged={judged} lod_checked={overall['lod_checked']} "
        f"explicitly_present={overall['explicitly_present']} "
        f"explicitly_absent={overall['explicitly_absent']} errors={overall['errors']}"
    )
    if judged:
        lod._log(f"counterfactual rate: {cf}/{judged} = {cf/judged:.1%}")


if __name__ == "__main__":
    main()
