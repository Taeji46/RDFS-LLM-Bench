"""Prompt builders for zero-shot task generation.

Level naming convention:
  Operation : NRP (Necessary Rule Presentation) — nrps internally for n=1, nrpm for n≥2
            | ARP (All-Rule Presentation)
  Rule info : full (name+def) | name (name only) | def (definition only)
  Format    : {operation}-{rule_info}  e.g. NRP-full, NRP-name, ARP-def
"""

from __future__ import annotations

import re

from shared.rule_defs import OPERATION_TYPE_ALIASES, RULE_DEFINITIONS, RULE_TEXT_BY_RULE_ID


def normalize_operation_type(operation_type: str) -> str:
    key = operation_type.strip().lower()
    if key not in OPERATION_TYPE_ALIASES:
        raise ValueError(f"Unknown operation type: {operation_type}")
    return OPERATION_TYPE_ALIASES[key]


def extract_rule_keys(rule_id: str) -> list[str]:
    """Convert rdfs2_3_7 -> [rdfs2, rdfs3, rdfs7]."""
    match = re.fullmatch(r"rdfs(\d+(?:_\d+)*)", rule_id.strip())
    if not match:
        return []

    nums = match.group(1).split("_")
    return [f"rdfs{n}" for n in nums if f"rdfs{n}" in RULE_DEFINITIONS]


def build_prompt(operation_type: str, premise_knowledge: str, rule_id: str) -> str:
    """Build an LLM input prompt from task fields."""
    op_type = normalize_operation_type(operation_type)
    rule_keys = extract_rule_keys(rule_id)

    # ── NRP (Necessary Rule Presentation) ────────────────────────
    if op_type == "NRP-full":
        if len(rule_keys) == 1:
            rule_text = RULE_TEXT_BY_RULE_ID.get(rule_id.strip())
            if not rule_text:
                raise ValueError(f"NRP-full (n=1) requires known rule_id mapping, got: {rule_id}")
            return _build_prompt_nrps_full(rule_id, rule_text, premise_knowledge)
        else:
            _require_rule_keys(rule_id, rule_keys)
            return _build_prompt_nrpm_full(premise_knowledge, rule_keys)

    if op_type == "NRP-name":
        _require_rule_keys(rule_id, rule_keys)
        if len(rule_keys) == 1:
            return _build_prompt_nrps_name(premise_knowledge, rule_keys)
        else:
            return _build_prompt_nrpm_name(premise_knowledge, rule_keys)

    if op_type == "NRP-def":
        if len(rule_keys) == 1:
            rule_text = RULE_TEXT_BY_RULE_ID.get(rule_id.strip())
            if not rule_text:
                raise ValueError(f"NRP-def (n=1) requires known rule_id mapping, got: {rule_id}")
            return _build_prompt_nrps_def(rule_text, premise_knowledge)
        else:
            _require_rule_keys(rule_id, rule_keys)
            return _build_prompt_nrpm_def(premise_knowledge, rule_keys)

    # ── ARP (All-Rule Presentation) ───────────────────────────────
    if op_type == "ARP-full":
        return _build_prompt_arp_full(premise_knowledge)

    if op_type == "ARP-name":
        return _build_prompt_arp_name(premise_knowledge)

    if op_type == "ARP-def":
        return _build_prompt_arp_def(premise_knowledge)

    raise ValueError(f"Unsupported operation type: {operation_type}")


def get_template_hash(operation_type: str, rule_id: str = "") -> str:
    """Return a short content hash of the prompt template for operation_type.

    Calls each internal template builder with empty placeholder values so the
    hash reflects only the template structure (surrounding instruction text),
    not any rule definitions or premise knowledge content.

    For NRP operations, rule_id is used to determine n (single vs multi),
    since nrps (n=1) and nrpm (n≥2) use different template structures.

    Returns a string like "t-1a2b3c4d".
    """
    import hashlib
    from shared.rule_defs import DEFAULT_SYSTEM_PROMPT
    op = normalize_operation_type(operation_type)

    _p = ""   # empty premise_knowledge
    _t = ""   # empty rule_text
    _ks: list[str] = []  # empty rule_keys
    n = len(extract_rule_keys(rule_id)) if rule_id else 0

    if op == "NRP-full":
        user_prompt = _build_prompt_nrps_full("", _t, _p) if n == 1 else _build_prompt_nrpm_full(_p, _ks)
    elif op == "NRP-name":
        user_prompt = _build_prompt_nrps_name(_p, _ks) if n == 1 else _build_prompt_nrpm_name(_p, _ks)
    elif op == "NRP-def":
        user_prompt = _build_prompt_nrps_def(_t, _p) if n == 1 else _build_prompt_nrpm_def(_p, _ks)
    elif op == "ARP-full":
        user_prompt = _build_prompt_arp_full(_p)
    elif op == "ARP-name":
        user_prompt = _build_prompt_arp_name(_p)
    elif op == "ARP-def":
        user_prompt = _build_prompt_arp_def(_p)
    else:
        raise ValueError(f"Unsupported operation type: {operation_type}")

    # Include op in fingerprint so that operation types whose builders collapse
    # to the same string with empty inputs (e.g. NRP-full vs NRP-def) still
    # receive distinct hashes, while all rule_ids within the same op_type share one.
    fingerprint = DEFAULT_SYSTEM_PROMPT + "\n---\n" + op + "\n---\n" + user_prompt
    return "t-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:8]


def _require_rule_keys(rule_id: str, rule_keys: list[str]) -> None:
    if not rule_keys:
        raise ValueError(f"Could not infer rule keys from rule_id: {rule_id}")


_NOTE_PLACEHOLDERS = (
    "Note: The variable names used in the rule (e.g., a, b, i, j, k, X, Y, Z, W) are placeholders and do not represent actual classes, properties, or instances. "
    "They are used solely for describing the rule structure. "
)
_NOTE_PLACEHOLDERS_PLURAL = (
    "Note: The variable names used in these rules (e.g., a, b, i, j, k, X, Y, Z, W) are placeholders and do not represent actual classes, properties, or instances. "
    "They are used solely for describing the rule structure. "
)
_TRIPLE_FORMAT = (
    "Enclose each triple in \"<\" and \">\". "
    "Never use the \"http://\" format in the triple. "
)
_SRA_OUTPUT_INSTRUCTION = (
    "At the end of your response, list all rule names you used in the format: [used_rules: rdfsN, ...]. "
    "Replace N with the actual rule numbers you applied. "
    "Enclose the list in \"[\" and \"]\", use the exact key name \"used_rules:\", and separate each rule name with a comma. "
    "Use only rule names from the following list: rdfs2, rdfs3, rdfs5, rdfs7, rdfs9, rdfs11. "
    "Output all triples that can be derived from these rules and do not include any additional text or descriptions. "
    "The only exception is the [used_rules: ...] line at the end of your response."
)
_SRA_DEF_OUTPUT_INSTRUCTION = (
    "At the end of your response, list all rule names you used in the format: [used_rules: ruleX, ...]. "
    "Replace X with the actual rule letters you applied (e.g., ruleA, ruleB, ruleC). "
    "Enclose the list in \"[\" and \"]\", use the exact key name \"used_rules:\", and separate each rule name with a comma. "
    "Use only rule names from ruleA to ruleF. "
    "Output all triples that can be derived from these rules and do not include any additional text or descriptions. "
    "The only exception is the [used_rules: ...] line at the end of your response."
)
_RULE_LABELS = ["ruleA", "ruleB", "ruleC", "ruleD", "ruleE", "ruleF"]

_HEADER_SINGLE = "Given the following rule and premise knowledge:\n"
_HEADER_PLURAL = "Given the following rules and premise knowledge:\n"
_INFER_SINGLE = "Solely based on this rule and the premise knowledge, output the inferred RDFS triples. "
_INFER_MULTI_COMBINE = "Solely based on these rules and the premise knowledge, output the inferred RDFS triples by combining these rules. "
_INFER_MULTI_SELECT = "Solely based on these rules and the premise knowledge, output the inferred RDFS triples by selecting and combining these rules as necessary. "
_OUTPUT_SINGLE = "Output all triples that can be derived from this rule and do not include any additional text or descriptions."
_OUTPUT_MULTI = "Output all triples that can be derived from these rules and do not include any additional text or descriptions."


# ── NRP single (n=1) ─────────────────────────────────────────────

def _build_prompt_nrps_full(rule_id: str, rule_text: str, premise_knowledge: str) -> str:
    """NRP-full n=1: rule name + definition."""
    return (
        _HEADER_SINGLE
        + f"Rule:\n{rule_id}: {rule_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


def _build_prompt_nrps_name(premise_knowledge: str, rule_keys: list[str]) -> str:
    """NRP-name n=1: rule name only."""
    rules_text = ", ".join(rule_keys)
    return (
        _HEADER_SINGLE
        + f"Rule: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


def _build_prompt_nrps_def(rule_text: str, premise_knowledge: str) -> str:
    """NRP-def n=1: rule definition only."""
    return (
        _HEADER_SINGLE
        + f"Rule: {rule_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


# ── NRP multi (n≥2) ──────────────────────────────────────────────

def _build_prompt_nrpm_full(premise_knowledge: str, rule_keys: list[str]) -> str:
    """NRP-full n≥2: rule names + definitions."""
    rules_text = "\n".join(f"{k}: {RULE_DEFINITIONS[k]}" for k in rule_keys)
    return (
        _HEADER_PLURAL
        + f"Rules:\n{rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS_PLURAL
        + _INFER_MULTI_COMBINE
        + _TRIPLE_FORMAT
        + _OUTPUT_MULTI
    )


def _build_prompt_nrpm_name(premise_knowledge: str, rule_keys: list[str]) -> str:
    """NRP-name n≥2: rule names only."""
    rules_text = ", ".join(rule_keys)
    return (
        _HEADER_PLURAL
        + f"Rules: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_MULTI_COMBINE
        + _TRIPLE_FORMAT
        + _OUTPUT_MULTI
    )


def _build_prompt_nrpm_def(premise_knowledge: str, rule_keys: list[str]) -> str:
    """NRP-def n≥2: rule definitions only."""
    rules_text = "\n".join(RULE_DEFINITIONS[k] for k in rule_keys)
    return (
        _HEADER_PLURAL
        + f"Rules:\n{rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS_PLURAL
        + _INFER_MULTI_COMBINE
        + _TRIPLE_FORMAT
        + _OUTPUT_MULTI
    )


# ── ARP (All-Rule Presentation) ──────────────────────────────────

def _build_prompt_arp_full(premise_knowledge: str) -> str:
    """ARP-full: all rule names + definitions."""
    rules_text = "\n".join(f"{k}: {v}" for k, v in RULE_DEFINITIONS.items())
    return (
        _HEADER_PLURAL
        + f"Rules:\n{rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS_PLURAL
        + _INFER_MULTI_SELECT
        + _TRIPLE_FORMAT
        + _SRA_OUTPUT_INSTRUCTION
    )


def _build_prompt_arp_name(premise_knowledge: str) -> str:
    """ARP-name: all rule names only."""
    rules_text = ", ".join(RULE_DEFINITIONS.keys())
    return (
        _HEADER_PLURAL
        + f"Rules: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_MULTI_SELECT
        + _TRIPLE_FORMAT
        + _SRA_OUTPUT_INSTRUCTION
    )


def _build_prompt_arp_def(premise_knowledge: str) -> str:
    """ARP-def: all rule definitions with anonymous labels (ruleA-ruleF)."""
    rules_text = "\n".join(
        f"{label}: {defn}"
        for label, defn in zip(_RULE_LABELS, RULE_DEFINITIONS.values())
    )
    return (
        _HEADER_PLURAL
        + f"Rules:\n{rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS_PLURAL
        + _INFER_MULTI_SELECT
        + _TRIPLE_FORMAT
        + _SRA_DEF_OUTPUT_INSTRUCTION
    )
