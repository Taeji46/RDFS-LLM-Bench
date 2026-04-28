import os
import uuid
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))

from _base import LOV_ENDPOINT, PROJECT_ROOT, balanced_sample, get_fetch_args, parse_bindings, query_hash, run_sparql, save_benchmark_sample

RULE = "rdfs5"
SOURCE = "lov"
GROUP_BY = "k"
DEFAULT_LIMIT = 400
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data/lod-samples/1-rule")

QUERY = """
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?i ?j ?k
    WHERE {
        ?i rdfs:subPropertyOf ?j .
        ?j rdfs:subPropertyOf ?k .
        FILTER(isIRI(?i) && isIRI(?j) && isIRI(?k))
        FILTER(!CONTAINS(STR(?i), "#") && !CONTAINS(STR(?j), "#") && !CONTAINS(STR(?k), "#"))
        FILTER(!regex(STR(?i), "[0-9]") && !regex(STR(?j), "[0-9]") && !regex(STR(?k), "[0-9]"))
    }
    ORDER BY RAND()
"""

FIELDS = ["i", "j", "k"]

_CAMEL_CASE = re.compile(r'^[a-z]+([A-Z][a-z]+)*$')
_SINGLE_WORD = re.compile(r'^[a-z]+$')


def _local_name(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _is_valid_property(term: str) -> bool:
    return bool(_CAMEL_CASE.match(term) or _SINGLE_WORD.match(term))


def row_filter(row: dict) -> bool:
    terms = [_local_name(row[f]) for f in FIELDS]
    if len(set(terms)) < len(terms):
        return False
    return all(_is_valid_property(t) for t in terms)


if __name__ == "__main__":
    args = get_fetch_args(RULE, SOURCE, DEFAULT_OUTPUT_DIR)
    qhash = query_hash(QUERY)

    print(f"Fetching entries for {RULE} from {LOV_ENDPOINT} ...")
    bindings = run_sparql(LOV_ENDPOINT, QUERY)
    rows = parse_bindings(bindings, FIELDS, row_filter=row_filter)

    sampled = balanced_sample(rows, group_by=GROUP_BY, limit=DEFAULT_LIMIT, seed=None)

    fetch_uid = "f-" + uuid.uuid4().hex[:8]
    metadata = {
        "endpoints": [LOV_ENDPOINT],
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
