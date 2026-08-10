"""Exact numeric helpers for evaluation/report metrics.

Metric arithmetic is carried as ``Fraction`` until serialization.  Canonical
CSV/JSON values are decimal strings rounded with ROUND_HALF_UP, so downstream
paper/table generation never depends on Python's binary floats or banker's
rounding.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from typing import Iterable

METRIC_QUANT = Decimal("0.000000000001")
TABLE_3DP_QUANT = Decimal("0.001")


def mean_fraction(values: Iterable[Fraction]) -> Fraction | None:
    vals = list(values)
    if not vals:
        return None
    return sum(vals, Fraction(0)) / len(vals)


def metric_to_decimal(value: Fraction, quant: Decimal = METRIC_QUANT) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        quant,
        rounding=ROUND_HALF_UP,
    )


def decimal_to_canonical_str(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def metric_to_str(value: Fraction) -> str:
    return decimal_to_canonical_str(metric_to_decimal(value))


def metric_from_str(value: object) -> Fraction | None:
    if value is None or value == "":
        return None
    if isinstance(value, Fraction):
        return value
    return Fraction(Decimal(str(value)))


def table_3dp_str(value: object) -> str:
    metric = metric_from_str(value)
    if metric is None:
        return ""
    rounded = metric_to_decimal(metric, TABLE_3DP_QUANT)
    return format(rounded, "0.3f")


def metric_to_excel_float(value: object) -> float:
    metric = metric_from_str(value)
    if metric is None:
        raise ValueError(f"not a metric value: {value!r}")
    return float(metric_to_decimal(metric))
