"""Fetch rdfs5 samples from Wikidata P1647 hierarchy + schema.org subPropertyOf.

Three patterns combined:
  1. Wikidata 3-hop:        wp_i  P1647  wp_j  P1647  wp_k
  2. schema.org Pattern 1:  schema_child  ⊑  schema_parent (≡ wp1)  wp1 P1647 wp2
  3. schema.org Pattern 2:  wp1  P1647  wp2 (≡ sp2)  sp2 ⊑ sp3

Licenses: Wikidata CC0, schema.org CC BY-SA 3.0
"""

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from _base import (
    PROJECT_ROOT,
    SCHEMA_NS,
    SCHEMA_NT_URL,
    WDT_ENDPOINT,
    all_distinct,
    balanced_sample,
    fetch_schema_subprop_pairs,
    fetch_wdt_schema_equivalences,
    get_fetch_args,
    parse_bindings,
    query_hash,
    run_sparql,
    save_benchmark_sample,
    to_property_name,
)

RULE = "rdfs5"
RULES = ['rdfs5']
SOURCE = "wdt+schema"
GROUP_BY = "k"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/1-rule")

WDT_3HOP_QUERY = """
    SELECT DISTINCT ?i ?iLabel ?j ?jLabel ?k ?kLabel WHERE {
        ?i wdt:P1647 ?j.
        ?j wdt:P1647 ?k.
        FILTER(?i != ?j && ?j != ?k && ?i != ?k)
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
"""

WDT_1HOP_QUERY = """
    SELECT ?prop ?propLabel ?parent ?parentLabel WHERE {
        ?prop wdt:P1647 ?parent.
        FILTER(?prop != ?parent)
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
"""

def _valid_labels(i_lbl: str, j_lbl: str, k_lbl: str) -> bool:
    i_n, j_n, k_n = to_property_name(i_lbl), to_property_name(j_lbl), to_property_name(k_lbl)
    return bool(i_n) and bool(j_n) and bool(k_n) and all_distinct(i_n, j_n, k_n)


def _name_key(i_lbl: str, j_lbl: str, k_lbl: str) -> tuple[str, str, str]:
    return to_property_name(i_lbl), to_property_name(j_lbl), to_property_name(k_lbl)


if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(WDT_3HOP_QUERY + WDT_1HOP_QUERY)

    all_entries: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()

    # ── 1. Wikidata 3-hop P1647 chains ─────────────────────────────────
    print("Fetching Wikidata 3-hop P1647 chains...")
    bindings_3hop = run_sparql(WDT_ENDPOINT, WDT_3HOP_QUERY)
    rows_3hop = parse_bindings(bindings_3hop, ["i", "iLabel", "j", "jLabel", "k", "kLabel"])
    print(f"  Raw: {len(rows_3hop)} bindings")
    count_wdt = 0
    for r in rows_3hop:
        if not _valid_labels(r["iLabel"], r["jLabel"], r["kLabel"]):
            continue
        key = _name_key(r["iLabel"], r["jLabel"], r["kLabel"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        all_entries.append({
            "i": r["i"], "i_label": r["iLabel"],
            "j": r["j"], "j_label": r["jLabel"],
            "k": r["k"], "k_label": r["kLabel"],
            "source": "wdt3hop",
        })
        count_wdt += 1
    print(f"  Added {count_wdt} Wikidata 3-hop chains")
    time.sleep(2)

    # ── 2. schema.org subPropertyOf hierarchy ─────────────────────────────
    print(f"Downloading schema.org N-Triples from {SCHEMA_NT_URL} ...")
    schema_pairs = fetch_schema_subprop_pairs()
    print(f"  Found {len(schema_pairs)} schema.org subPropertyOf pairs")
    schema_child_to_parents: dict[str, list[str]] = {}
    schema_parent_to_children: dict[str, list[str]] = {}
    for child, parent in schema_pairs:
        schema_child_to_parents.setdefault(child, []).append(parent)
        schema_parent_to_children.setdefault(parent, []).append(child)

    # ── 3. Wikidata P1628 ≡ schema.org equivalences ───────────────────────
    print("Fetching Wikidata P1628 ≡ schema.org equivalences...")
    schema_to_wdt_uri, wdt_to_schema_local = fetch_wdt_schema_equivalences()
    print(f"  {len(schema_to_wdt_uri)} Wikidata-schema.org equivalences")
    time.sleep(2)

    # ── 4. Wikidata 1-hop P1647 pairs ─────────────────────────────────────
    print("Fetching Wikidata 1-hop P1647 pairs...")
    bindings_1hop = run_sparql(WDT_ENDPOINT, WDT_1HOP_QUERY)
    rows_1hop = parse_bindings(bindings_1hop, ["prop", "propLabel", "parent", "parentLabel"])
    wdt_parents: dict[str, list[tuple[str, str]]] = {}
    wdt_prop_labels: dict[str, str] = {}
    for r in rows_1hop:
        wdt_parents.setdefault(r["prop"], []).append((r["parent"], r["parentLabel"]))
        wdt_prop_labels[r["prop"]] = r["propLabel"]
    print(f"  {sum(len(v) for v in wdt_parents.values())} 1-hop pairs")

    # ── 5. Pattern 1: schema_child → schema_parent (≡wp1) → wp1's wikidata parent ──
    count_p1 = 0
    for schema_parent_local, (wdt_equiv_uri, wdt_equiv_lbl) in schema_to_wdt_uri.items():
        schema_children = schema_parent_to_children.get(schema_parent_local, [])
        wdt_grandparents = wdt_parents.get(wdt_equiv_uri, [])
        for child_local in schema_children:
            for gp_uri, gp_lbl in wdt_grandparents:
                if not _valid_labels(child_local, schema_parent_local, gp_lbl):
                    continue
                key = _name_key(child_local, schema_parent_local, gp_lbl)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_entries.append({
                    "i": SCHEMA_NS + child_local,
                    "j": SCHEMA_NS + schema_parent_local,
                    "j_wdt": wdt_equiv_uri, "j_wdt_label": wdt_equiv_lbl,
                    "k": gp_uri, "k_label": gp_lbl,
                    "source": "schema_p1",
                })
                count_p1 += 1
    print(f"Pattern 1 chains added: {count_p1}")

    # ── 6. Pattern 2: wp1 → wp2 (≡sp2) → sp2's schema parent ──────────────
    count_p2 = 0
    for wp1_uri, parents in wdt_parents.items():
        wp1_lbl = wdt_prop_labels.get(wp1_uri, "")
        if not wp1_lbl:
            continue
        for wp2_uri, wp2_lbl in parents:
            sp2_local = wdt_to_schema_local.get(wp2_uri)
            if not sp2_local:
                continue
            for sp3_local in schema_child_to_parents.get(sp2_local, []):
                if not _valid_labels(wp1_lbl, sp2_local, sp3_local):
                    continue
                key = _name_key(wp1_lbl, sp2_local, sp3_local)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_entries.append({
                    "i": wp1_uri, "i_label": wp1_lbl,
                    "j": SCHEMA_NS + sp2_local,
                    "j_wdt": wp2_uri, "j_wdt_label": wp2_lbl,
                    "k": SCHEMA_NS + sp3_local,
                    "source": "schema_p2",
                })
                count_p2 += 1
    print(f"Pattern 2 chains added: {count_p2}")

    print(f"\nTotal unique chains: {len(all_entries)}")

    sampled = balanced_sample(all_entries, group_by=GROUP_BY, limit=DEFAULT_LIMIT, seed=42)

    source_counts: dict[str, int] = {}
    for e in sampled:
        source_counts[e["source"]] = source_counts.get(e["source"], 0) + 1
    print(f"Source breakdown of sample: {source_counts}")

    fetch_uid = "f-" + uuid.uuid4().hex[:8]
    metadata = {
        "endpoints": [WDT_ENDPOINT, SCHEMA_NT_URL],
        "fetched_at": args.date,
        "pattern_id": RULE,
        "rules": RULES,
        "source": SOURCE,
        "group_by": GROUP_BY,
        "limit": DEFAULT_LIMIT,
        "queryhash8": qhash,
        "fetch_uid": fetch_uid,
    }

    save_benchmark_sample(
        sampled, metadata, args.output_dir,
        RULE, SOURCE, GROUP_BY, None, qhash, args.date,
    )
