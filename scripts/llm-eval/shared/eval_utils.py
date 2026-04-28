"""Evaluation utilities for LLM output assessment."""

from __future__ import annotations

import re


def extract_rdf_triples(text: str) -> set[str]:
    """Extract RDF triples from text in <s, p, o> format.

    Returns a set of strings like "s, p, o" (angle brackets stripped).
    Only accepts the canonical "<s, p, o>" format (strict mode).
    """
    raw_matches = re.findall(r'<[^>]+>', text)
    triples: set[str] = set()
    for raw in raw_matches:
        cleaned = (
            raw
            .replace('< ', '<')
            .replace(' >', '>')
            .replace('"', '')
            .strip('<>')
        )
        triples.add(cleaned)
    return triples


def parse_triple(triple_str: str) -> tuple[str, str, str] | None:
    """Parse a canonical "s, p, o" string into (s, p, o).

    Splits on commas; expects exactly 3 parts.
    Returns None if the string cannot be parsed as a triple.
    """
    parts = triple_str.split(', ', 2)
    if len(parts) == 3:
        return (parts[0], parts[1], parts[2])
    return None


def match_triple_flex(candidate: str, s: str, p: str, o: str) -> bool:
    """Check whether candidate contains s, p, o in order with only separators between.

    Separators are: comma, space, angle brackets.
    This allows format variants like "<s,p,o>", "<s p o>", "<s , p , o>" etc.
    to be matched against the canonical (s, p, o) parsed from expected output.
    """
    sep = set(', <>')

    i = candidate.find(s)
    if i == -1:
        return False
    if any(c not in sep for c in candidate[:i]):
        return False

    j = candidate.find(p, i + len(s))
    if j == -1:
        return False
    if any(c not in sep for c in candidate[i + len(s):j]):
        return False

    k = candidate.find(o, j + len(p))
    if k == -1:
        return False
    if any(c not in sep for c in candidate[j + len(p):k]):
        return False

    if any(c not in sep for c in candidate[k + len(o):]):
        return False

    return True


def compute_flex_metrics(
    expected_triples: set[str],
    model_candidates: list[str],
    premise_triples: set[str],
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 using flex (order-based) triple matching.

    expected_triples and premise_triples are canonical "s, p, o" strings.
    model_candidates are raw strings extracted from model output (content of <...>).
    """
    # Parse expected and premise into (s, p, o) tuples
    expected_parsed = [parse_triple(t) for t in expected_triples]
    expected_parsed = [t for t in expected_parsed if t is not None]

    premise_parsed = [parse_triple(t) for t in premise_triples]
    premise_parsed = [t for t in premise_parsed if t is not None]

    # Filter out candidates that match any premise triple
    def _is_premise(cand: str) -> bool:
        return any(match_triple_flex(cand, s, p, o) for s, p, o in premise_parsed)

    filtered = [c for c in model_candidates if not _is_premise(c)]

    if not expected_parsed:
        return 0.0, 0.0, 0.0

    # Recall: how many expected triples are matched by at least one candidate
    tp_recall = sum(
        1 for s, p, o in expected_parsed
        if any(match_triple_flex(c, s, p, o) for c in filtered)
    )
    # Precision: how many candidates match at least one expected triple
    tp_precision = sum(
        1 for c in filtered
        if any(match_triple_flex(c, s, p, o) for s, p, o in expected_parsed)
    )

    precision = tp_precision / len(filtered) if filtered else 0.0
    recall    = tp_recall / len(expected_parsed)
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


_RULE_LABEL_TO_RDFS: dict[str, str] = {
    "ruleA": "rdfs2",
    "ruleB": "rdfs3",
    "ruleC": "rdfs5",
    "ruleD": "rdfs7",
    "ruleE": "rdfs9",
    "ruleF": "rdfs11",
}


def extract_used_rules(text: str) -> list[str]:
    """Extract rule names from [used_rules: ...] in model output.

    Normalizes ruleX labels (ruleA-ruleF) to rdfsN names so that
    SRA-def outputs can be compared against rdfsN expected_rules.
    """
    match = re.search(r'\[used_rules:\s*([^\]]+)\]', text)
    if not match:
        return []
    raw = [r.strip() for r in match.group(1).split(',')]
    return [_RULE_LABEL_TO_RDFS.get(r, r) for r in raw]


def compute_set_metrics(
    expected: set[str] | list[str],
    predicted: set[str] | list[str],
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 by exact set comparison."""
    expected_set = set(expected)
    predicted_set = set(predicted)

    tp = len(expected_set & predicted_set)
    fp = len(predicted_set - expected_set)
    fn = len(expected_set - predicted_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


# Operations that require rule identification evaluation
SRA_RULE_EVAL_OPS = {"SRA-full", "SRA-name", "SRA-def"}
