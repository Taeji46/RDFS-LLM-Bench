import os
import uuid
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from _base import DBP_ENDPOINT, PROJECT_ROOT, all_distinct, balanced_sample, get_fetch_args, parse_bindings, query_hash, run_sparql, save_benchmark_sample

RULE = "rdfs11"
SOURCE = "dbp"
GROUP_BY = "z"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/1-rule")

QUERY = """
    SELECT DISTINCT ?x ?y ?z
    WHERE {
        ?x rdfs:subClassOf ?y .
        ?y rdfs:subClassOf ?z .
        FILTER(STRSTARTS(STR(?x), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?y), "http://dbpedia.org/ontology/"))
        FILTER(STRSTARTS(STR(?z), "http://dbpedia.org/ontology/"))
        FILTER(REGEX(STRAFTER(STR(?x), "http://dbpedia.org/ontology/"), "^[A-Za-z]"))
        FILTER(REGEX(STRAFTER(STR(?y), "http://dbpedia.org/ontology/"), "^[A-Za-z]"))
        FILTER(REGEX(STRAFTER(STR(?z), "http://dbpedia.org/ontology/"), "^[A-Za-z]"))
    }
    ORDER BY RAND()
"""

FIELDS = ["x", "y", "z"]

if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(QUERY)

    print(f"Fetching entries for {RULE} from {DBP_ENDPOINT} ...")
    bindings = run_sparql(DBP_ENDPOINT, QUERY)
    rows = parse_bindings(bindings, FIELDS)
    rows = [r for r in rows if all_distinct(r["x"], r["y"], r["z"])]

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
