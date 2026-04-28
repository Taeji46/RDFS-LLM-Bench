"""
Generate RVA (Random Vocabulary Assignment) dataset.

Each entry is built by randomly sampling DBpedia local names
(resources / properties / classes) and assigning them to the
term slots of a rule without any real-world semantic relationship.

Vocabulary pools (resources, properties, classes) are fetched from DBpedia
once at the start and shared across all rules.

Distinctness constraints match the legacy gen_rnd_* scripts exactly:
  - instance slots (a, b): all distinct
  - property slots (i, j, k): all distinct only when rule semantics require it
  - class slots (x, y, z, w): all distinct only when rule semantics require it
(see _DISTINCT_CHECK for per-rule details)
"""

import os
import random
import sys
from collections.abc import Callable
from datetime import date

from SPARQLWrapper import JSON, SPARQLWrapper

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared._base import (
    ALL_RULES,
    RULE_CONFIGS,
    all_distinct,
    make_dataset_entry,
    save_dataset,
)

# ──────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────
DBP_ENDPOINT = "https://dbpedia.org/sparql"
DEFAULT_LIMIT = 400
VOCAB_POOL_SIZE = 5000

# ──────────────────────────────────────────────────────────────────
# Term variable lists per rule
# (same ordering and keys as build_terms in RULE_CONFIGS)
# ──────────────────────────────────────────────────────────────────
_RULE_VARS: dict[str, list[str]] = {
    "rdfs2":      ["a", "b", "i", "x"],
    "rdfs3":      ["a", "b", "i", "x"],
    "rdfs5":      ["i", "j", "k"],
    "rdfs7":      ["a", "b", "i", "j"],
    "rdfs9":      ["a", "x", "y"],
    "rdfs11":     ["x", "y", "z"],
    "rdfs2_3":    ["a", "b", "i", "x", "y"],
    "rdfs2_7":    ["a", "b", "i", "j", "x"],
    "rdfs2_9":    ["a", "b", "i", "x", "y"],
    "rdfs3_7":    ["a", "b", "i", "j", "x"],
    "rdfs3_9":    ["a", "b", "i", "x", "y"],
    "rdfs5_7":    ["a", "b", "i", "j", "k"],
    "rdfs9_11":   ["a", "x", "y", "z"],
    "rdfs2_3_7":  ["a", "b", "i", "j", "x", "y"],
    "rdfs2_3_9":  ["a", "b", "i", "x", "y", "z", "w"],
    "rdfs2_5_7":  ["a", "b", "i", "j", "k", "x"],
    "rdfs2_9_11": ["a", "b", "i", "x", "y", "z"],
    "rdfs3_5_7":  ["a", "b", "i", "j", "k", "x"],
    "rdfs3_9_11": ["a", "b", "i", "x", "y", "z"],
}

# ──────────────────────────────────────────────────────────────────
# Distinctness constraints per rule (mirrors legacy gen_rnd_* exactly)
# ──────────────────────────────────────────────────────────────────
_DISTINCT_CHECK: dict[str, "Callable[[dict], bool]"] = {
    "rdfs2":      lambda t: all_distinct(t["a"], t["b"]),
    "rdfs3":      lambda t: all_distinct(t["a"], t["b"]),
    "rdfs5":      lambda t: all_distinct(t["i"], t["j"], t["k"]),
    "rdfs7":      lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"]),
    "rdfs9":      lambda t: all_distinct(t["x"], t["y"]),
    "rdfs11":     lambda t: all_distinct(t["x"], t["y"], t["z"]),
    "rdfs2_3":    lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"]),
    "rdfs2_7":    lambda t: all_distinct(t["a"], t["b"]),
    "rdfs2_9":    lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"]),
    "rdfs3_7":    lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"]),
    "rdfs3_9":    lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"]),
    "rdfs5_7":    lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"], t["k"]),
    "rdfs9_11":   lambda t: all_distinct(t["x"], t["y"], t["z"]),
    "rdfs2_3_7":  lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"]) and all_distinct(t["x"], t["y"]),
    "rdfs2_3_9":  lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"], t["z"], t["w"]),
    "rdfs2_5_7":  lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"], t["k"]),
    "rdfs2_9_11": lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"], t["z"]),
    "rdfs3_5_7":  lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["i"], t["j"], t["k"]),
    "rdfs3_9_11": lambda t: all_distinct(t["a"], t["b"]) and all_distinct(t["x"], t["y"], t["z"]),
}


# ──────────────────────────────────────────────────────────────────
# Vocabulary fetch
# ──────────────────────────────────────────────────────────────────
def _run_sparql(query: str) -> list[str]:
    sparql = SPARQLWrapper(DBP_ENDPOINT, agent="RDFS-LLM-Bench/1.0 (research project)")
    sparql.setReturnFormat(JSON)
    sparql.setQuery(query)
    results: dict = sparql.query().convert()  # type: ignore[assignment]
    return [b["localName"]["value"] for b in results["results"]["bindings"]]  # type: ignore[index]


def fetch_resources(limit: int) -> list[str]:
    print(f"Fetching {limit} resources from DBpedia...")
    query = f"""
        SELECT DISTINCT (REPLACE(STR(?a), ".*/", "") AS ?localName)
        WHERE {{
            ?a a ?type .
            ?a rdfs:label ?label .
            FILTER(lang(?label) = 'en')
            FILTER(isIRI(?a))
            FILTER(STRSTARTS(STR(?a), "http://dbpedia.org/resource/"))
            FILTER(!regex(REPLACE(STR(?a), ".*/", ""), "[\\u0600-\\u06FF]"))
        }}
        ORDER BY RAND()
        LIMIT {limit}
    """
    result = _run_sparql(query)
    print(f"  Retrieved {len(result)} resources")
    return result


def fetch_properties(limit: int) -> list[str]:
    print(f"Fetching {limit} properties from DBpedia...")
    query = f"""
        SELECT DISTINCT (REPLACE(STR(?property), ".*/", "") AS ?localName)
        WHERE {{
            ?property a rdf:Property .
            ?property rdfs:label ?label .
            FILTER(lang(?label) = 'en')
            FILTER(
                STRSTARTS(STR(?property), "http://dbpedia.org/ontology/") ||
                STRSTARTS(STR(?property), "http://dbpedia.org/property/")
            )
            FILTER(isIRI(?property))
            FILTER(!regex(REPLACE(STR(?property), ".*/", ""), "[\\u0600-\\u06FF]"))
        }}
        ORDER BY RAND()
        LIMIT {limit}
    """
    result = _run_sparql(query)
    print(f"  Retrieved {len(result)} properties")
    return result


def fetch_classes(limit: int) -> list[str]:
    print(f"Fetching {limit} classes from DBpedia...")
    query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT (REPLACE(STR(?class), ".*/", "") AS ?localName)
        WHERE {{
            ?class rdfs:subClassOf* owl:Thing .
            ?class rdfs:label ?label .
            FILTER(lang(?label) = 'en')
            FILTER(isIRI(?class))
            FILTER(STRSTARTS(STR(?class), "http://dbpedia.org/ontology/"))
            FILTER(!regex(REPLACE(STR(?class), ".*/", ""), "[\\u0600-\\u06FF]"))
        }}
        ORDER BY RAND()
        LIMIT {limit}
    """
    result = _run_sparql(query)
    print(f"  Retrieved {len(result)} classes")
    return result


# ──────────────────────────────────────────────────────────────────
# Term sampling
# ──────────────────────────────────────────────────────────────────
def _sample_terms(
    vars: list[str],
    resources: list[str],
    properties: list[str],
    classes: list[str],
) -> dict[str, str]:
    t = {}
    for v in vars:
        if v in ("a", "b"):
            t[v] = random.choice(resources)
        elif v in ("i", "j", "k"):
            t[v] = random.choice(properties)
        else:  # x, y, z, w
            t[v] = random.choice(classes)
    return t


# ──────────────────────────────────────────────────────────────────
# Per-rule dataset builder
# ──────────────────────────────────────────────────────────────────
def build_rva(
    rule: str,
    resources: list[str],
    properties: list[str],
    classes: list[str],
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    cfg = RULE_CONFIGS[rule]
    vars_ = _RULE_VARS[rule]
    check = _DISTINCT_CHECK[rule]
    dataset: list[dict] = []

    while len(dataset) < limit:
        t = _sample_terms(vars_, resources, properties, classes)
        if not check(t):
            continue
        dataset.append(
            make_dataset_entry(
                premise_knowledge=cfg["build_premise"](t),
                expected_output=cfg["build_conclusion"](t),
            )
        )

    return dataset


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    build_date = date.today().strftime("%Y%m%d")

    resources = fetch_resources(VOCAB_POOL_SIZE)
    properties = fetch_properties(VOCAB_POOL_SIZE)
    classes = fetch_classes(VOCAB_POOL_SIZE)

    for rule in ALL_RULES:
        print(f"\n=== {rule} ===")
        dataset = build_rva(rule, resources, properties, classes)
        save_dataset(
            dataset,
            rule,
            "rva",
            build_date=build_date,
        )


if __name__ == "__main__":
    main()
