import os
import uuid
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from collections import defaultdict

from _base import DBP_ENDPOINT, WDT_ENDPOINT, PROJECT_ROOT, all_distinct, fetch_wdt_equivalent_dbp_properties, get_fetch_args, parse_bindings, query_hash, run_sparql, save_benchmark_sample

RULE = "rdfs2_3_7"
SOURCE = "wdt"
GROUP_BY = "xy"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/3-rule")

WDT_QUERY = """
    SELECT ?i ?iLabel ?j ?jLabel
    WHERE {
        ?i wdt:P1647 ?j.
        SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
    }
"""

DBP_QUERY_TEMPLATE = """
    SELECT DISTINCT ?a ?b ?x ?y WHERE {{
        ?a <{prop}> ?b .
        <{prop}> rdfs:domain ?x .
        <{prop}> rdfs:range ?y .
        FILTER(isIRI(?a) && isIRI(?b))
        FILTER(STRSTARTS(STR(?a), "http://dbpedia.org/resource/"))
        FILTER(STRSTARTS(STR(?b), "http://dbpedia.org/resource/"))
    }}
    ORDER BY RAND()
"""

if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(WDT_QUERY + DBP_QUERY_TEMPLATE)

    print("Fetching property hierarchy from Wikidata...")
    hierarchy = run_sparql(WDT_ENDPOINT, WDT_QUERY)
    total = len(hierarchy)
    print(f"Found {total} hierarchy entries")

    grouped: defaultdict[tuple, list] = defaultdict(list)

    for idx, h in enumerate(hierarchy, 1):
        i = h["i"]["value"]
        j = h["j"]["value"]
        i_label = h.get("iLabel", {}).get("value", "")
        j_label = h.get("jLabel", {}).get("value", "")

        print(f"Processing {idx}/{total}: {i}")

        time.sleep(0.5)
        dbp_props = fetch_wdt_equivalent_dbp_properties(i)
        if not dbp_props:
            continue

        for dbp_prop in dbp_props:
            try:
                instances = run_sparql(DBP_ENDPOINT, DBP_QUERY_TEMPLATE.format(prop=dbp_prop))
            except Exception as e:
                print(f"Error fetching instances for {dbp_prop}: {e}")
                continue

            for row in parse_bindings(instances, ["a", "b", "x", "y"]):
                if not all_distinct(row["a"], row["b"]) or not all_distinct(row["x"], row["y"]):
                    continue

                entry = {
                    "a": row["a"],
                    "b": row["b"],
                    "i": i,
                    "i_label": i_label,
                    "i_dbp": dbp_prop,
                    "j": j,
                    "j_label": j_label,
                    "x": row["x"],
                    "y": row["y"],
                }
                grouped[(row["x"], row["y"])].append(entry)

    all_entries = [e for group in grouped.values() for e in group]
    print(f"{len(all_entries)} rows available")

    sampled = []
    while len(sampled) < min(DEFAULT_LIMIT, len(all_entries)):
        for key in list(grouped.keys()):
            if grouped[key]:
                sampled.append(grouped[key].pop(0))
                if len(sampled) >= DEFAULT_LIMIT:
                    break
            if not grouped[key]:
                del grouped[key]

    print(f"Sampled {len(sampled)} entries (seed=None)")

    fetch_uid = "f-" + uuid.uuid4().hex[:8]
    metadata = {
        "endpoints": [WDT_ENDPOINT, DBP_ENDPOINT],
        "fetched_at": args.date,
        "rule": RULE,
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
