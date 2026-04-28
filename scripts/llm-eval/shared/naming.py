"""Path naming helpers for llm-eval pipeline."""

from __future__ import annotations

import re


def sanitize_for_path(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
