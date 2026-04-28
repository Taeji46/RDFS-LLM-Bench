import os
import uuid
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from collections import defaultdict

from _base import DBP_ENDPOINT, PROJECT_ROOT, all_distinct, balanced_sample, get_fetch_args, query_hash, run_sparql, save_benchmark_sample

RULE = "rdfs2_9"
SOURCE = "dbp"
GROUP_BY = "y"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/2-rule")

QUERY = """
    SELECT DISTINCT ?a ?b ?i ?x ?y
    WHERE {
        ?a ?i ?b .
        ?i rdfs:domain ?x .
        ?x rdfs:subClassOf ?y .
        FILTER(isIRI(?a) && isIRI(?i) && isIRI(?b) && isIRI(?x) && isIRI(?y))
        FILTER(STRSTARTS(STR(?a), "http://dbpedia.org/resource/"))
        FILTER(STRSTARTS(STR(?i), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?b), "http://dbpedia.org/resource/"))
        FILTER(STRSTARTS(STR(?x), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?y), "http://dbpedia.org/ontology/"))
    }
    ORDER BY RAND()
"""

if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(QUERY)

    print(f"Fetching entries for {RULE} from {DBP_ENDPOINT} ...")
    bindings = run_sparql(DBP_ENDPOINT, QUERY)

    rows = []
    for binding in bindings:
        if not all(v in binding for v in ["a", "b", "i", "x", "y"]):
            continue
        rows.append({v: binding[v]["value"] for v in ["a", "b", "i", "x", "y"]})
    rows = [r for r in rows if all_distinct(r["a"], r["b"]) and all_distinct(r["x"], r["y"])]

    sampled = balanced_sample(rows, group_by=GROUP_BY, limit=DEFAULT_LIMIT, seed=None)

    fetch_uid = "f-" + uuid.uuid4().hex[:8]
    metadata = {
        "endpoints": [DBP_ENDPOINT],
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
