"""Evaluation utilities for LLM output assessment."""

from __future__ import annotations

from fractions import Fraction
import re


def extract_rdf_candidates(text: str) -> list[str]:
    """Extract and clean angle-bracketed RDF candidate strings.

    The cleaning behavior is shared by strict and flex evaluation.  The list
    preserves duplicate model outputs so flex evaluation can retain an audit
    trail before applying set semantics.
    """
    raw_matches = re.findall(r'<[^>]+>', text)
    return [
        raw
        .replace('< ', '<')
        .replace(' >', '>')
        .replace('"', '')
        .strip('<>')
        for raw in raw_matches
    ]


def extract_rdf_triples(text: str) -> set[str]:
    """Extract RDF triples from text in <s, p, o> format.

    Returns a set of strings like "s, p, o" (angle brackets stripped).
    Only accepts the canonical "<s, p, o>" format (strict mode).
    """
    return set(extract_rdf_candidates(text))


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
    """Match a complete candidate while tolerating comma/whitespace separators.

    At least one comma or Unicode whitespace character is required between
    terms.  Leading and trailing whitespace is allowed; other characters are
    not.  Terms are escaped so they are always matched literally.

    This allows format variants like "<s,p,o>", "<s p o>", "<s , p , o>" etc.
    to be matched against the canonical (s, p, o) parsed from expected output.
    """
    pattern = rf"\s*{re.escape(s)}[,\s]+{re.escape(p)}[,\s]+{re.escape(o)}\s*"
    return re.fullmatch(pattern, candidate) is not None


def normalize_flex_candidate(candidate: str) -> str:
    """Normalize the same separator variations accepted by flex matching.

    Outer whitespace is removed before separator runs are folded.  This keeps
    invalid leading or trailing commas distinguishable from valid whitespace.
    """
    return re.sub(r'[,\s]+', ' ', candidate.strip())


def _parse_reference_triples(
    triples: set[str],
    *,
    label: str,
) -> dict[str, tuple[str, str, str]]:
    """Parse canonical reference triples, failing instead of silently skipping."""
    parsed: dict[str, tuple[str, str, str]] = {}
    for triple in triples:
        parts = parse_triple(triple)
        if parts is None:
            raise ValueError(f"unparseable {label} triple: {triple!r}")
        parsed[triple] = parts
    return parsed


def compute_flex_metrics(
    expected_triples: set[str],
    model_candidates: list[str],
    premise_triples: set[str],
) -> tuple[Fraction, Fraction, Fraction]:
    """Compute precision, recall, F1 using flex (order-based) triple matching.

    expected_triples and premise_triples are canonical "s, p, o" strings.
    model_candidates are raw strings extracted from model output (content of <...>).
    """
    precision, recall, f1, _, _, _, _ = compute_flex_metrics_with_filtered(
        expected_triples, model_candidates, premise_triples
    )
    return precision, recall, f1


def compute_flex_metrics_with_filtered(
    expected_triples: set[str],
    model_candidates: list[str],
    premise_triples: set[str],
) -> tuple[
    Fraction,
    Fraction,
    Fraction,
    list[str],
    list[str],
    set[str],
    set[str],
]:
    """Compute flex metrics with RDF-set semantics and return an audit trace.

    Returns metrics followed by premise-filtered raw candidates, normalized
    scored candidates, matched target triples, and normalized unmatched
    candidates.  Correct and incorrect duplicate outputs each count once.
    """
    expected_parsed = _parse_reference_triples(expected_triples, label="target")
    premise_parsed = _parse_reference_triples(premise_triples, label="premise")

    premise_filtered: list[str] = []
    candidate_matches: list[tuple[str, tuple[str, ...]]] = []
    for candidate in model_candidates:
        premise_matches = tuple(
            triple
            for triple, (s, p, o) in premise_parsed.items()
            if match_triple_flex(candidate, s, p, o)
        )
        target_matches = tuple(
            triple
            for triple, (s, p, o) in expected_parsed.items()
            if match_triple_flex(candidate, s, p, o)
        )

        if len(target_matches) > 1:
            raise ValueError(
                f"flex candidate matches multiple target triples: "
                f"candidate={candidate!r}, targets={target_matches!r}"
            )
        if premise_matches and target_matches:
            raise ValueError(
                f"flex candidate matches both premise and target triples: "
                f"candidate={candidate!r}, premises={premise_matches!r}, "
                f"targets={target_matches!r}"
            )
        if premise_matches:
            continue

        premise_filtered.append(candidate)
        candidate_matches.append((candidate, target_matches))

    # All candidates in one normalized class must have the same match result.
    matches_by_normalized: dict[str, tuple[str, ...]] = {}
    for candidate, target_matches in candidate_matches:
        normalized = normalize_flex_candidate(candidate)
        previous = matches_by_normalized.setdefault(normalized, target_matches)
        if previous != target_matches:
            raise ValueError(
                f"normalized flex candidates disagree on match result: "
                f"normalized={normalized!r}, first={previous!r}, "
                f"current={target_matches!r}"
            )

    matched_targets = {
        target
        for target_matches in matches_by_normalized.values()
        for target in target_matches
    }
    unmatched_candidates = {
        normalized
        for normalized, target_matches in matches_by_normalized.items()
        if not target_matches
    }
    scored_candidates = sorted(matches_by_normalized)

    precision_denominator = len(matched_targets) + len(unmatched_candidates)
    precision = (
        Fraction(len(matched_targets), precision_denominator)
        if precision_denominator
        else Fraction(0)
    )
    recall = (
        Fraction(len(matched_targets), len(expected_parsed))
        if expected_parsed
        else Fraction(0)
    )
    f1        = (
        Fraction(2) * precision * recall / (precision + recall)
        if precision + recall > 0
        else Fraction(0)
    )
    return (
        precision,
        recall,
        f1,
        premise_filtered,
        scored_candidates,
        matched_targets,
        unmatched_candidates,
    )


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
    ARP-def outputs can be compared against rdfsN expected_rules.
    """
    match = re.search(r'\[used_rules:\s*([^\]]+)\]', text)
    if not match:
        return []
    raw = [r.strip() for r in match.group(1).split(',')]
    return [_RULE_LABEL_TO_RDFS.get(r, r) for r in raw]


def compute_set_metrics(
    expected: set[str] | list[str],
    predicted: set[str] | list[str],
) -> tuple[Fraction, Fraction, Fraction]:
    """Compute precision, recall, F1 by exact set comparison."""
    expected_set = set(expected)
    predicted_set = set(predicted)

    tp = len(expected_set & predicted_set)
    fp = len(predicted_set - expected_set)
    fn = len(expected_set - predicted_set)

    precision = Fraction(tp, tp + fp) if (tp + fp) > 0 else Fraction(0)
    recall    = Fraction(tp, tp + fn) if (tp + fn) > 0 else Fraction(0)
    f1        = (
        Fraction(2) * precision * recall / (precision + recall)
        if precision + recall > 0
        else Fraction(0)
    )
    return precision, recall, f1


# Prompting conditions that require rule identification evaluation
ARP_RULE_EVAL_OPS = {"ARP-full", "ARP-name", "ARP-def"}
