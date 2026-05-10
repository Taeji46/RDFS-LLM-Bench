import os
import uuid
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from collections import defaultdict

from _base import DBP_ENDPOINT, PROJECT_ROOT, all_distinct, get_fetch_args, parse_bindings, query_hash, run_sparql, save_benchmark_sample

RULE = "rdfs2_3_9"
RULES = ['rdfs2', 'rdfs3', 'rdfs9']
SOURCE = "dbp"
GROUP_BY = "zw"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/3-rule")

QUERY = """
    SELECT DISTINCT ?a ?b ?i ?x ?y ?z ?w
    WHERE {
        ?a ?i ?b .
        ?i rdfs:domain ?x .
        ?i rdfs:range ?y .
        ?x rdfs:subClassOf ?z .
        ?y rdfs:subClassOf ?w .
        FILTER(isIRI(?a) && isIRI(?i) && isIRI(?b) && isIRI(?x) && isIRI(?y) && isIRI(?z) && isIRI(?w))
        FILTER(STRSTARTS(STR(?a), "http://dbpedia.org/resource/"))
        FILTER(STRSTARTS(STR(?i), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?b), "http://dbpedia.org/resource/"))
        FILTER(STRSTARTS(STR(?x), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?y), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?z), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?w), "http://dbpedia.org/ontology/"))
    }
    ORDER BY RAND()
"""

FIELDS = ["a", "b", "i", "x", "y", "z", "w"]

if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(QUERY)

    print(f"Fetching entries for {RULE} from {DBP_ENDPOINT} ...")
    bindings = run_sparql(DBP_ENDPOINT, QUERY)
    rows = parse_bindings(bindings, FIELDS)

    # dedup filter: a != b, and x, y, z, w must all be distinct
    rows = [r for r in rows if all_distinct(r["a"], r["b"]) and all_distinct(r["x"], r["y"], r["z"], r["w"])]
    print(f"{len(rows)} rows available after dedup filter")

    # balanced sampling grouped by (z, w)
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["z"], row["w"])].append(row)

    sampled = []
    while len(sampled) < min(DEFAULT_LIMIT, len(rows)):
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
        "endpoints": [DBP_ENDPOINT],
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
