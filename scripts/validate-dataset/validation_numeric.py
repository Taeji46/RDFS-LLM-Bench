"""Exact numeric serialization for validation artifacts."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

RATE_QUANT = Decimal("0.000000000001")


def rate_fraction_str(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{numerator}/{denominator}"


def rate_decimal_str(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        RATE_QUANT,
        rounding=ROUND_HALF_UP,
    )
    return format(value, "f").rstrip("0").rstrip(".") or "0"
