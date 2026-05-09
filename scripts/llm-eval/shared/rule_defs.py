"""Rule and prompt-level constants for llm-eval pipeline."""

from __future__ import annotations

RULE_DEFINITIONS: dict[str, str] = {
    "rdfs2": "if <i, rdfs:domain, X> and <a, i, b> then <a, rdf:type, X>",
    "rdfs3": "if <i, rdfs:range, X> and <a, i, b> then <b, rdf:type, X>",
    "rdfs5": "if <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> then <i, rdfs:subPropertyOf, k>",
    "rdfs7": "if <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, j, b>",
    "rdfs9": "if <X, rdfs:subClassOf, Y> and <a, rdf:type, X> then <a, rdf:type, Y>",
    "rdfs11": "if <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> then <X, rdfs:subClassOf, Z>",
}

RULE_NAMES: tuple[str, ...] = tuple(RULE_DEFINITIONS.keys())

# Verbatim rule texts for lv1 prompts (single/double/triple).
RULE_TEXT_BY_RULE_ID: dict[str, str] = {
    "rdfs2": "if <i, rdfs:domain, X> and <a, i, b> then <a, rdf:type, X>",
    "rdfs3": "if <i, rdfs:range, X> and <a, i, b> then <b, rdf:type, X>",
    "rdfs5": "if <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> then <i, rdfs:subPropertyOf, k>",
    "rdfs7": "if <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, j, b>",
    "rdfs9": "if <X, rdfs:subClassOf, Y> and <a, rdf:type, X> then <a, rdf:type, Y>",
    "rdfs11": "if <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> then <X, rdfs:subClassOf, Z>",
    "rdfs2_3": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <a, i, b> then <a, rdf:type, X> and <b, rdf:type, Y>",
    "rdfs2_7": "if <i, rdfs:domain, X> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, rdf:type, X> and <a, j, b>",
    "rdfs2_9": "if <i, rdfs:domain, X> and <X, rdfs:subClassOf, Y> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Y>",
    "rdfs3_7": "if <i, rdfs:range, X> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <b, rdf:type, X> and <a, j, b>",
    "rdfs3_9": "if <i, rdfs:range, X> and <X, rdfs:subClassOf, Y> and <a, i, b> then <b, rdf:type, X> and <b, rdf:type, Y>",
    "rdfs5_7": "if <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
    "rdfs9_11": "if <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, rdf:type, X> then <a, rdf:type, Y> and <a, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
    "rdfs2_3_7": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <i, rdfs:subPropertyOf, j> and <a, i, b> then <a, rdf:type, X> and <b, rdf:type, Y> and <a, j, b>",
    "rdfs2_3_9": "if <i, rdfs:domain, X> and <i, rdfs:range, Y> and <X, rdfs:subClassOf, Z> and <Y, rdfs:subClassOf, W> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Z> and <b, rdf:type, Y> and <b, rdf:type, W>",
    "rdfs2_5_7": "if <i, rdfs:domain, X> and <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <a, rdf:type, X> and <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
    "rdfs2_9_11": "if <i, rdfs:domain, X> and <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, i, b> then <a, rdf:type, X> and <a, rdf:type, Y> and <a, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
    "rdfs3_5_7": "if <i, rdfs:range, X> and <i, rdfs:subPropertyOf, j> and <j, rdfs:subPropertyOf, k> and <a, i, b> then <b, rdf:type, X> and <i, rdfs:subPropertyOf, k> and <a, j, b> and <a, k, b>",
    "rdfs3_9_11": "if <i, rdfs:range, X> and <X, rdfs:subClassOf, Y> and <Y, rdfs:subClassOf, Z> and <a, i, b> then <b, rdf:type, X> and <b, rdf:type, Y> and <b, rdf:type, Z> and <X, rdfs:subClassOf, Z>",
}

PROMPTING_CONDITIONS: tuple[str, ...] = (
    "NRP-full", "NRP-name", "NRP-def",
    "ARP-full", "ARP-name", "ARP-def",
)

PROMPTING_CONDITION_ALIASES: dict[str, str] = {
    "nrp-full": "NRP-full",
    "nrp-name": "NRP-name",
    "nrp-def":  "NRP-def",
    "arp-full": "ARP-full",
    "arp-name": "ARP-name",
    "arp-def":  "ARP-def",
}

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
