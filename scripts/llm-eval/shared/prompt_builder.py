"""Prompt builders for zero-shot task generation.

Level naming convention:
  Operation : ESRA (Explicit Single-Rule Application)
            | EMRA (Explicit Multi-Rule Application)
            | SRA  (Selective Rule Application)
  Rule info : full (name+def) | name (name only) | def (definition only)
  Format    : {operation}-{rule_info}  e.g. ESRA-full, EMRA-name, SRA-def

Prompt template strings in this module are kept verbatim with
`legacy/batch_api/create_batch_dataset.py` prompt builders
for the variants that existed in the legacy system.
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

    # ── ESRA (Explicit Single-Rule Application) ───────────────────
    if op_type == "ESRA-full":
        rule_text = RULE_TEXT_BY_RULE_ID.get(rule_id.strip())
        if not rule_text:
            raise ValueError(f"ESRA-full requires known rule_id mapping, got: {rule_id}")
        return _build_prompt_esra_full(rule_id, rule_text, premise_knowledge)

    if op_type == "ESRA-name":
        _require_rule_keys(rule_id, rule_keys)
        return _build_prompt_esra_name(premise_knowledge, rule_keys)

    if op_type == "ESRA-def":
        rule_text = RULE_TEXT_BY_RULE_ID.get(rule_id.strip())
        if not rule_text:
            raise ValueError(f"ESRA-def requires known rule_id mapping, got: {rule_id}")
        return _build_prompt_esra_def(rule_text, premise_knowledge)

    # ── EMRA (Explicit Multi-Rule Application) ────────────────────
    if op_type == "EMRA-full":
        _require_rule_keys(rule_id, rule_keys)
        return _build_prompt_emra_full(premise_knowledge, rule_keys)

    if op_type == "EMRA-name":
        _require_rule_keys(rule_id, rule_keys)
        return _build_prompt_emra_name(premise_knowledge, rule_keys)

    if op_type == "EMRA-def":
        _require_rule_keys(rule_id, rule_keys)
        return _build_prompt_emra_def(premise_knowledge, rule_keys)

    # ── SRA (Selective Rule Application) ─────────────────────────
    if op_type == "SRA-full":
        return _build_prompt_sra_full(premise_knowledge)

    if op_type == "SRA-name":
        return _build_prompt_sra_name(premise_knowledge)

    if op_type == "SRA-def":
        return _build_prompt_sra_def(premise_knowledge)

    raise ValueError(f"Unsupported operation type: {operation_type}")


def get_template_hash(operation_type: str) -> str:
    """Return a short content hash of the prompt template for operation_type.

    Calls each internal template builder with empty placeholder values so the
    hash reflects only the template structure (surrounding instruction text),
    not any rule definitions or premise knowledge content.

    Returns a string like "t-1a2b3c4d".
    """
    import hashlib
    from shared.rule_defs import DEFAULT_SYSTEM_PROMPT
    op = normalize_operation_type(operation_type)

    _p = ""   # empty premise_knowledge
    _t = ""   # empty rule_text
    _ks: list[str] = []  # empty rule_keys

    if op == "ESRA-full":
        user_prompt = _build_prompt_esra_full("", _t, _p)
    elif op == "ESRA-name":
        user_prompt = _build_prompt_esra_name(_p, _ks)
    elif op == "ESRA-def":
        user_prompt = _build_prompt_esra_def(_t, _p)
    elif op == "EMRA-full":
        user_prompt = _build_prompt_emra_full(_p, _ks)
    elif op == "EMRA-name":
        user_prompt = _build_prompt_emra_name(_p, _ks)
    elif op == "EMRA-def":
        user_prompt = _build_prompt_emra_def(_p, _ks)
    elif op == "SRA-full":
        user_prompt = _build_prompt_sra_full(_p)
    elif op == "SRA-name":
        user_prompt = _build_prompt_sra_name(_p)
    elif op == "SRA-def":
        user_prompt = _build_prompt_sra_def(_p)
    else:
        raise ValueError(f"Unsupported operation type: {operation_type}")

    # Include op in fingerprint so that operation types whose builders collapse
    # to the same string with empty inputs (e.g. EMRA-full vs EMRA-def) still
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


# ── ESRA (Explicit Single-Rule Application) ───────────────────────

def _build_prompt_esra_full(rule_id: str, rule_text: str, premise_knowledge: str) -> str:
    """ESRA-full: rule name + definition."""
    return (
        _HEADER_SINGLE
        + f"Rule:\n{rule_id}: {rule_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


def _build_prompt_esra_name(premise_knowledge: str, rule_keys: list[str]) -> str:
    """ESRA-name: rule name only."""
    rules_text = ", ".join(rule_keys)
    return (
        _HEADER_SINGLE
        + f"Rule: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


def _build_prompt_esra_def(rule_text: str, premise_knowledge: str) -> str:
    """ESRA-def: rule definition only."""
    return (
        _HEADER_SINGLE
        + f"Rule: {rule_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _NOTE_PLACEHOLDERS
        + _INFER_SINGLE
        + _TRIPLE_FORMAT
        + _OUTPUT_SINGLE
    )


# ── EMRA (Explicit Multi-Rule Application) ────────────────────────

def _build_prompt_emra_full(premise_knowledge: str, rule_keys: list[str]) -> str:
    """EMRA-full: rule names + definitions."""
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


def _build_prompt_emra_name(premise_knowledge: str, rule_keys: list[str]) -> str:
    """EMRA-name: rule names only."""
    rules_text = ", ".join(rule_keys)
    return (
        _HEADER_PLURAL
        + f"Rules: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_MULTI_COMBINE
        + _TRIPLE_FORMAT
        + _OUTPUT_MULTI
    )


def _build_prompt_emra_def(premise_knowledge: str, rule_keys: list[str]) -> str:
    """EMRA-def: rule definitions only."""
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


# ── SRA (Selective Rule Application) ─────────────────────────────

def _build_prompt_sra_full(premise_knowledge: str) -> str:
    """SRA-full: all rule names + definitions."""
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


def _build_prompt_sra_name(premise_knowledge: str) -> str:
    """SRA-name: all rule names only."""
    rules_text = ", ".join(RULE_DEFINITIONS.keys())
    return (
        _HEADER_PLURAL
        + f"Rules: {rules_text}\n"
        + f"Premise Knowledge: {premise_knowledge}\n"
        + _INFER_MULTI_SELECT
        + _TRIPLE_FORMAT
        + _SRA_OUTPUT_INSTRUCTION
    )


def _build_prompt_sra_def(premise_knowledge: str) -> str:
    """SRA-def: all rule definitions with anonymous labels (ruleA-ruleF)."""
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
