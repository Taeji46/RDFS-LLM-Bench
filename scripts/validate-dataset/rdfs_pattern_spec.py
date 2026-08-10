"""Shared RDFS benchmark premise structure.

This module has no endpoint/query behavior. It only defines the rendered
premise parser and the ordered triple-role specification used by RVA, LS, and
GS validators.
"""

from __future__ import annotations

import re


def parse_triples(premise: str) -> list[tuple[str, str, str]]:
    out = []
    for raw in re.findall(r"<([^>]+)>", premise):
        parts = raw.split(", ")
        if len(parts) == 3:
            out.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return out


def triple_text(triple: tuple[str, str, str]) -> str:
    return f"<{triple[0]}, {triple[1]}, {triple[2]}>"


# Expected predicate per role (used to validate the premise matches the spec).
ROLE_PRED = {
    "domain": "rdfs:domain",
    "range": "rdfs:range",
    "subClassOf": "rdfs:subClassOf",
    "subPropertyOf": "rdfs:subPropertyOf",
    "type": "rdf:type",
    # "instance" predicate is a property local name (anything else).
}


# Hardcoded premise structure per rule (ordered roles). Derived from the
# generators; one entry per inference pattern.
PATTERN_SPEC = {
    # 1-rule
    "rdfs2": ["domain", "instance"],
    "rdfs3": ["range", "instance"],
    "rdfs5": ["subPropertyOf", "subPropertyOf"],
    "rdfs7": ["subPropertyOf", "instance"],
    "rdfs9": ["subClassOf", "type"],
    "rdfs11": ["subClassOf", "subClassOf"],
    # 2-rule
    "rdfs2_3": ["domain", "range", "instance"],
    "rdfs2_7": ["domain", "subPropertyOf", "instance"],
    "rdfs2_9": ["domain", "subClassOf", "instance"],
    "rdfs3_7": ["range", "subPropertyOf", "instance"],
    "rdfs3_9": ["range", "subClassOf", "instance"],
    "rdfs5_7": ["subPropertyOf", "subPropertyOf", "instance"],
    "rdfs9_11": ["subClassOf", "subClassOf", "type"],
    # 3-rule
    "rdfs2_3_7": ["domain", "range", "subPropertyOf", "instance"],
    "rdfs2_3_9": ["domain", "range", "subClassOf", "subClassOf", "instance"],
    "rdfs2_5_7": ["domain", "subPropertyOf", "subPropertyOf", "instance"],
    "rdfs2_9_11": ["domain", "subClassOf", "subClassOf", "instance"],
    "rdfs3_5_7": ["range", "subPropertyOf", "subPropertyOf", "instance"],
    "rdfs3_9_11": ["range", "subClassOf", "subClassOf", "instance"],
}
