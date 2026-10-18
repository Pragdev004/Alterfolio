"""Display formatting (presentation only), stdlib only: INR with Indian grouping, percentages, prices, plain decimals, IST dates.

Rounding happens here and nowhere else (ROUND_HALF_EVEN); facts, fingerprints and stored values stay exact. A missing value is
the word "Unavailable" with a reason, never a formatted zero. Spec: docs/specs/013a-analysis-read-api.md section 4.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.timezones import IST

UNAVAILABLE = "Unavailable"
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal(100)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_KINDS = ("inr", "inr_lower_bound", "price", "ratio", "ratio_fees_excluded", "count", "plain")
_NOTES = {"inr_lower_bound": " (lower bound)", "ratio_fees_excluded": " (fees excluded)"}


def _q(d: Decimal) -> Decimal:
    q = d.quantize(_TWO, rounding=ROUND_HALF_EVEN)
    return Decimal("0.00") if q == 0 else q  # never "-0.00"


def format_percent(ratio: str | Decimal) -> str:
    """A ratio as a percentage: 0.003728 -> '0.37%'."""
    q = _q(Decimal(ratio) * _HUNDRED)
    return f"{q:f}%"


def _group(whole: str) -> str:
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def format_inr(amount: str | Decimal) -> str:
    """INR with 2 decimals and Indian grouping: 123456.78 -> '₹1,23,456.78'; negatives '-₹1,23,456.78'."""
    q = _q(Decimal(amount))
    whole, frac = f"{abs(q):f}".split(".")
    return f"{'-' if q < 0 else ''}₹{_group(whole)}.{frac}"


def format_price(amount: str | Decimal) -> str:
    """A per-unit price: 2 dp, but up to 4 dp below one rupee (trailing zeros trimmed to 2 dp). A nonzero price that would round
    to zero at 4 dp is shown as '<₹0.0001', never as a zero price."""
    d = Decimal(amount)
    if abs(d) >= 1:
        return format_inr(d)
    q = d.quantize(_FOUR, rounding=ROUND_HALF_EVEN)
    if q == 0:
        return "<₹0.0001" if d != 0 else "₹0.00"
    text = f"{abs(q):f}"
    while text.endswith("0") and len(text.split(".")[1]) > 2:
        text = text[:-1]
    return f"{'-' if q < 0 else ''}₹{text}"


def format_plain(value: str | Decimal) -> str:
    """The exact decimal without exponent or trailing zeros (quantities): '10.000000' -> '10'. No rounding."""
    d = Decimal(value)
    if not d.is_finite():
        raise ValueError("not a finite decimal")
    text = f"{d.normalize():f}" if d != 0 else "0"
    return "0" if text in ("-0", "") else text


def format_date(d: date) -> str:
    """'16 Oct 2026' (no zero padding on the day)."""
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def format_datetime_ist(moment: datetime) -> str:
    """'16 Oct 2026, 10:30 IST' from an aware timestamp."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    local = moment.astimezone(IST)
    return f"{format_date(local.date())}, {local:%H:%M} IST"


def date_object(d: date) -> dict:
    return {"iso": d.isoformat(), "display": format_date(d)}


def number(value: str | Decimal | None, kind: str, reason: str | None = None) -> dict:
    """{value, display, unavailable_reason}. `value` is the exact canonical text or None; a None value always carries a reason."""
    if kind not in _KINDS:
        raise ValueError(f"unknown display kind {kind!r}")
    if value is None:
        return {"value": None, "display": UNAVAILABLE, "unavailable_reason": reason or "not available"}
    d = Decimal(value)
    if not d.is_finite():
        raise ValueError("a displayed number must be finite")
    text = format(d, "f") if isinstance(value, Decimal) else value
    if kind.startswith("inr"):
        shown = format_inr(d)
    elif kind == "price":
        shown = format_price(d)
    elif kind.startswith("ratio"):
        shown = format_percent(d)
    else:
        shown = format_plain(d)
    return {"value": text, "display": shown + _NOTES.get(kind, ""), "unavailable_reason": None}
