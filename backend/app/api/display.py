"""Display formatting (presentation only): percentages, INR with Indian grouping. Rounding happens here, never in facts.

Facts, fingerprints and stored values stay exact; this module only renders them for people. ROUND_HALF_EVEN, 2 decimals.
"""

from decimal import ROUND_HALF_EVEN, Decimal

from app.analyst.types import UNAVAILABLE, Fact

_TWO = Decimal("0.01")
_HUNDRED = Decimal(100)
_RATIO_SUFFIXES = ("mean_excess", "mean_percentile", "ci_lower", "ci_upper", ".percentile", ".excess", "actual_return")
_UNIT_NOTES = {"INR_LOWER_BOUND": " (lower bound)", "RATIO_FEES_EXCLUDED": " (fees excluded)"}


def _q(d: Decimal) -> Decimal:
    q = d.quantize(_TWO, rounding=ROUND_HALF_EVEN)
    return Decimal("0.00") if q == 0 else q  # never "-0.00"


def format_percent(ratio: str | Decimal) -> str:
    """A ratio as a percentage: 0.003728 -> '0.37%'."""
    q = _q(Decimal(ratio) * _HUNDRED)
    return f"{q:f}%"


def format_inr(amount: str | Decimal) -> str:
    """INR with 2 decimals and Indian grouping: 123456.78 -> '₹1,23,456.78'; negatives '-₹1,23,456.78'."""
    q = _q(Decimal(amount))
    whole, frac = f"{abs(q):f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{'-' if q < 0 else ''}₹{','.join([*groups, tail])}.{frac}"


def display_value(name: str, value: str, unit: str = "") -> str:
    """The user-facing text of one fact value. Unavailable is shown as 'Unavailable', never formatted as 0."""
    if value == UNAVAILABLE:
        return UNAVAILABLE
    if unit.startswith("INR"):
        return format_inr(value) + _UNIT_NOTES.get(unit, "")
    if unit.startswith("RATIO") or name.endswith(_RATIO_SUFFIXES):
        return format_percent(value) + _UNIT_NOTES.get(unit, "")
    return value


def render_fact(fact: Fact) -> str:
    return display_value(fact.name, fact.value, fact.unit)
