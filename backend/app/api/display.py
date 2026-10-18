"""Display formatting for the analyst: re-exports the pure formatters (they live in `domain/display.py`) and renders facts.

Facts, fingerprints and stored values stay exact; rounding happens only in the formatters. ROUND_HALF_EVEN, 2 decimals.
"""

from app.analyst.types import UNAVAILABLE, Fact
from app.domain.display import format_inr, format_percent, format_percentile

_PERCENTILE_SUFFIXES = ("mean_percentile", ".percentile")  # positions: whole percents, as in the analysis API
_RATIO_SUFFIXES = ("mean_excess", "ci_lower", "ci_upper", ".excess", "actual_return")
_UNIT_NOTES = {"INR_LOWER_BOUND": " (lower bound)", "RATIO_FEES_EXCLUDED": " (fees excluded)"}

__all__ = ["display_value", "format_inr", "format_percent", "format_percentile", "render_fact"]


def display_value(name: str, value: str, unit: str = "") -> str:
    """The user-facing text of one fact value. Unavailable is shown as 'Unavailable', never formatted as 0."""
    if value == UNAVAILABLE:
        return UNAVAILABLE
    if unit.startswith("INR"):
        return format_inr(value) + _UNIT_NOTES.get(unit, "")
    if name.endswith(_PERCENTILE_SUFFIXES):
        return format_percentile(value)
    if unit.startswith("RATIO") or name.endswith(_RATIO_SUFFIXES):
        return format_percent(value) + _UNIT_NOTES.get(unit, "")
    return value


def render_fact(fact: Fact) -> str:
    return display_value(fact.name, fact.value, fact.unit)
