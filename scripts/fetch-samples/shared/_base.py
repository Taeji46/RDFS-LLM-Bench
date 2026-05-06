"""
Common logic for fetch-samples scripts.

DBpedia rules:
    Use `get_fetch_args()`, `run_sparql()`, `parse_bindings()`,
    `balanced_sample()`, and `save_benchmark_sample()`.

Wikidata + DBpedia multi-step rules (rdfs7, rdfs2_7, rdfs3_7, ...):
    Use `get_fetch_args()`, `run_sparql()`, `fetch_wdt_equivalent_dbp_properties()`,
    `balanced_sample()`, and `save_benchmark_sample()`.

Wikidata + schema.org rule (rdfs5):
    Use `fetch_schema_subprop_pairs()` and `fetch_wdt_schema_equivalences()`
    in addition to the Wikidata SPARQL helpers.
"""

import argparse
import hashlib
import json
import os
import random
import time
from collections import defaultdict
from datetime import date
from typing import Callable

from SPARQLWrapper import JSON, SPARQLWrapper

DBP_ENDPOINT = "https://dbpedia.org/sparql"
WDT_ENDPOINT = "https://query.wikidata.org/sparql"
SCHEMA_NS = "https://schema.org/"
SCHEMA_NT_URL = "https://schema.org/version/latest/schemaorg-current-https.nt"
DBP_QUERY_TIMEOUT_MS = 120000
HTTP_SOCKET_TIMEOUT_SEC = 130


def all_distinct(*vals) -> bool:
    """Return True if all values are distinct (no duplicates)."""
    return len(set(vals)) == len(vals)


def query_hash(query: str) -> str:
    """Compute 8-char MD5 hash of a SPARQL query string for file identification."""
    return hashlib.md5(query.strip().encode("utf-8")).hexdigest()[:8]

# scripts/fetch-samples/shared/_base.py から3階層上がプロジェクトルート
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Re-export `to_property_name` from build-dataset/shared/_base.py so fetch scripts can use it
# without duplicating the camelCase logic.
import importlib.util as _importlib_util  # noqa: E402

_BUILD_BASE_PATH = os.path.join(PROJECT_ROOT, "scripts", "build-dataset", "shared", "_base.py")
_spec = _importlib_util.spec_from_file_location("_build_dataset_base", _BUILD_BASE_PATH)
assert _spec is not None and _spec.loader is not None, f"Cannot load {_BUILD_BASE_PATH}"
_build_base = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_build_base)
to_property_name = _build_base.to_property_name


def get_fetch_args(rule: str, source: str, default_output_dir: str) -> argparse.Namespace:
    """Args for fetch-samples scripts. No --limit: limit is hardcoded per script."""
    parser = argparse.ArgumentParser(description=f"Fetch and sample LOD entries for {rule} from {source}")
    parser.add_argument("--output-dir", default=default_output_dir, help="Output directory")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"), help="Fetch date (YYYYMMDD)")
    return parser.parse_args()


def run_sparql(endpoint: str, query: str) -> list[dict]:
    """Run a SPARQL query and return raw bindings."""
    sparql = SPARQLWrapper(endpoint, agent="RDFS-LLM-Bench/1.0 (research project; https://github.com/)")
    sparql.setReturnFormat(JSON)
    sparql.setQuery(query)

    # DBpedia(Virtuoso) accepts `timeout` in milliseconds as a query parameter.
    if "dbpedia.org/sparql" in endpoint:
        try:
            sparql.addParameter("timeout", str(DBP_QUERY_TIMEOUT_MS))
        except Exception:
            pass

    # Client-side socket timeout (seconds).
    if hasattr(sparql, "setTimeout"):
        sparql.setTimeout(HTTP_SOCKET_TIMEOUT_SEC)

    results: dict = sparql.query().convert()  # type: ignore[assignment]
    return results["results"]["bindings"]


def parse_bindings(
    bindings: list[dict],
    fields: list[str],
    row_filter: Callable[[dict], bool] | None = None,
) -> list[dict]:
    """
    Extract fields from raw SPARQL bindings.

    Args:
        bindings:   Raw SPARQL result bindings.
        fields:     Variable names to extract (e.g. ["a", "b", "i", "x"]).
        row_filter: Optional function (row: dict) -> bool for custom filtering.

    Returns:
        List of dicts with extracted field values.
    """
    rows = []
    for binding in bindings:
        if not all(v in binding for v in fields):
            continue
        row = {v: binding[v]["value"] for v in fields}
        if row_filter is not None and not row_filter(row):
            continue
        rows.append(row)
    return rows


def balanced_sample(rows: list[dict], group_by: str, limit: int, seed: int | None = 42) -> list[dict]:
    """
    Round-robin sampling grouped by `group_by` field.

    Works on any list of dicts — use after `parse_bindings()` for simple rules,
    or after manually building entries for Wikidata multi-step rules.

    Args:
        rows:     List of entry dicts.
        group_by: Field name to group by for balanced sampling.
        limit:    Max number of entries to return.
        seed:     Random seed for shuffling within each group (default 42).
                  Pass None to skip shuffling (e.g. v1 where ORDER BY RAND() provides randomness).

    Returns:
        Balanced list of entry dicts.
    """
    print(f"{len(rows)} rows available")

    grouped = defaultdict(list)
    for row in rows:
        grouped[row[group_by]].append(row)

    if seed is not None:
        rng = random.Random(seed)
        for key in grouped:
            rng.shuffle(grouped[key])

    balanced = []
    while len(balanced) < min(limit, len(rows)):
        for key in list(grouped.keys()):
            if grouped[key]:
                balanced.append(grouped[key].pop(0))
                if len(balanced) >= limit:
                    break
            if not grouped[key]:
                del grouped[key]

    print(f"Sampled {len(balanced)} entries (seed={seed})")
    return balanced



def fetch_wdt_equivalent_dbp_properties(property_uri: str) -> list[str]:
    """
    Fetch DBpedia equivalent properties for a Wikidata property via P1628.
    Common to all Wikidata + DBpedia multi-step rules.

    Args:
        property_uri: Wikidata property URI.

    Returns:
        List of DBpedia ontology URIs (filtered to dbpedia.org/ontology/).
    """
    query = f"""
        SELECT ?equivalentProperty WHERE {{
            ?property wdt:P1628 ?equivalentProperty.
            FILTER(STR(?property) = "{property_uri}")
        }}
    """
    for attempt in range(1, 11):
        try:
            bindings = run_sparql(WDT_ENDPOINT, query)
            return [
                b["equivalentProperty"]["value"]
                for b in bindings
                if b["equivalentProperty"]["value"].startswith("http://dbpedia.org/ontology/")
            ]
        except Exception as e:
            if attempt < 10:
                wait = attempt * 5
                print(f"  Attempt {attempt}/10 failed for {property_uri}: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  All 10 attempts failed for {property_uri}: {e}")
    return []


def fetch_wdt_schema_equivalences() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """
    Bulk-fetch all Wikidata properties that have a schema.org equivalent via P1628.

    Returns:
        (schema_local_to_wdt, wdt_uri_to_schema_local):
            schema_local_to_wdt maps schema.org local names to (wdt_uri, wdt_label).
            wdt_uri_to_schema_local maps Wikidata URIs back to schema.org local names.
    """
    query = """
        SELECT ?prop ?propLabel ?schemaProp WHERE {
            ?prop wdt:P1628 ?schemaProp.
            FILTER(STRSTARTS(STR(?schemaProp), "https://schema.org/"))
            SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
    """
    bindings = run_sparql(WDT_ENDPOINT, query)
    schema_to_wdt: dict[str, tuple[str, str]] = {}
    wdt_to_schema: dict[str, str] = {}
    for b in bindings:
        wdt_uri = b.get("prop", {}).get("value", "")
        wdt_lbl = b.get("propLabel", {}).get("value", "")
        schema_uri = b.get("schemaProp", {}).get("value", "")
        schema_local = schema_uri.rstrip("/").rsplit("/", 1)[-1]
        if wdt_uri and schema_local:
            schema_to_wdt[schema_local] = (wdt_uri, wdt_lbl)
            wdt_to_schema[wdt_uri] = schema_local
    return schema_to_wdt, wdt_to_schema


def fetch_schema_subprop_pairs() -> list[tuple[str, str]]:
    """
    Download schema.org N-Triples and extract rdfs:subPropertyOf pairs
    where both subject and object are in the schema.org namespace.

    Returns:
        List of (child_local, parent_local) tuples (URI local names).
    """
    import re
    import urllib.request

    req = urllib.request.Request(SCHEMA_NT_URL, headers={"User-Agent": "RDFS-LLM-Bench/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content = resp.read().decode("utf-8")
    pattern = re.compile(
        r"<([^>]+)>\s+<http://www\.w3\.org/2000/01/rdf-schema#subPropertyOf>\s+<([^>]+)>"
    )
    pairs: list[tuple[str, str]] = []
    for line in content.splitlines():
        if "subPropertyOf" not in line:
            continue
        m = pattern.match(line)
        if not m:
            continue
        s_uri, o_uri = m.group(1), m.group(2)
        if s_uri.startswith(SCHEMA_NS) and o_uri.startswith(SCHEMA_NS):
            child = s_uri.rstrip("/").rsplit("/", 1)[-1]
            parent = o_uri.rstrip("/").rsplit("/", 1)[-1]
            if child and parent and child != parent:
                pairs.append((child, parent))
    return pairs



def save_benchmark_sample(
    entries: list[dict],
    metadata: dict,
    output_dir: str,
    rule: str,
    source: str,
    group_by: str,
    seed: int | None,
    queryhash8: str,
    build_date: str,
) -> str:
    """Save benchmark sample to JSON file. Returns output path.

    Filename: benchmark-sample__{rule}__n{count}__{fetch_uid}.json
    fetch_uid must be pre-generated by the caller and included in metadata as "fetch_uid".
    All provenance details (source, endpoints, group_by, seed, queryhash8, fetched_at)
    are stored in metadata inside the file.
    """
    fetch_uid = metadata["fetch_uid"]

    metadata["count"] = len(entries)

    output = {
        "metadata": metadata,
        "entries": entries,
    }

    os.makedirs(output_dir, exist_ok=True)
    filename = f"lod-sample__{rule}__n{len(entries)}__{fetch_uid}.json"
    output_path = os.path.join(output_dir, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"Saved {len(entries)} entries to {output_path}")
    return output_path


