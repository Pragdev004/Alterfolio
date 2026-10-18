"""Display formatting (presentation only), stdlib only: INR with Indian grouping, percentages, prices, plain decimals, IST dates.

Rounding happens here and nowhere else (ROUND_HALF_EVEN); facts, fingerprints and stored values stay exact. A missing value is
the word "Unavailable" with a reason, never a formatted zero. Spec: docs/specs/013a-analysis-read-api.md section 4.
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.timezones import IST

UNAVAILABLE = "Unavailable"
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")
_HUNDRED = Decimal(100)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ONE = Decimal(1)
_KINDS = ("inr", "inr_lower_bound", "price", "ratio", "ratio_fees_excluded", "percentile", "count", "plain")
_NOTES = {"inr_lower_bound": " (lower bound)", "ratio_fees_excluded": " (fees excluded)"}


def _q(d: Decimal) -> Decimal:
    q = d.quantize(_TWO, rounding=ROUND_HALF_EVEN)
    return Decimal("0.00") if q == 0 else q  # never "-0.00"


def format_percent(ratio: str | Decimal) -> str:
    """A ratio as a percentage: 0.003728 -> '0.37%'."""
    q = _q(Decimal(ratio) * _HUNDRED)
    return f"{q:f}%"


def format_percentile(ratio: str | Decimal) -> str:
    """A percentile as a whole percentage (half-even): 0.612 -> '61%'. Percentiles are positions, so no decimals."""
    q = (Decimal(ratio) * _HUNDRED).quantize(_ONE, rounding=ROUND_HALF_EVEN)
    return "0%" if q == 0 else f"{q:f}%"


def direction(value: str | Decimal | None) -> str | None:
    """'ahead' | 'behind' | 'level' from the sign of an excess; None when there is no value."""
    if value is None:
        return None
    d = Decimal(value)
    return "ahead" if d > 0 else "behind" if d < 0 else "level"


def interval_direction(mean: str | Decimal | None, lower: str | Decimal | None, upper: str | Decimal | None) -> str | None:
    """Direction of an aggregate: 'inconclusive' when its interval touches or crosses zero, else the sign of the mean."""
    if mean is None:
        return None
    if lower is not None and upper is not None and Decimal(lower) <= 0 <= Decimal(upper):
        return "inconclusive"
    return direction(mean)


def direction_text(word: str | None) -> str | None:
    """The words shown for a direction; an inconclusive aggregate has no arrow or colour, only this sentence."""
    return "not distinguishable from zero" if word == "inconclusive" else word


_CODE = re.compile(r"^([A-Z][A-Z0-9_]+)(?:: (.*))?$", re.DOTALL)
_TRIPS_DETAIL = re.compile(r"(\d+) trips? available, (\d+) needed")
_CODE_TEXT = {
    # 007 luck test and its candidate exclusions (wording works for a trip or for an alternative)
    "NOT_CLOSED_AT_AS_OF": "This trip had not closed by the chosen date.",
    "CORPORATE_ACTION": "A split, bonus or dividend in this period would distort the prices.",
    "CORPORATE_ACTION_UNKNOWN": "Splits, bonuses and dividends have not been checked for this listing.",
    "CORPORATE_ACTION_COVERAGE_UNDECLARED":
        "Which listings have had splits, bonuses or dividends has not been reviewed, so luck is not computed.",
    "NO_TRIP_SERIES": "No price history is available for the traded stock.",
    "MISSING_BAR": "A price is missing on the opening or closing date.",
    "INSUFFICIENT_HISTORY": "There is not enough price history before the trip opened.",
    "INSUFFICIENT_ALTERNATIVES": "Too few alternatives had usable prices to draw portfolios.",
    "NIFTY_POOL_TOO_SMALL": "Too few Nifty 50 members had usable prices to draw portfolios.",
    "NO_MEMBERSHIP": "Nifty 50 membership is not set up, so this comparison cannot be made.",
    "NO_AVAILABLE_TRIPS": "No trip has a result for this comparison yet.",
    "SAME_AS_TRADED": "This is the stock you traded.",
    "NO_SERIES": "No price history is available for it.",
    "NO_ENTRY_BAR": "It had no price on the day the trip opened.",
    "NOT_IN_UNIVERSE": "It is not in the list of alternatives.",
    "NO_EXIT_BAR": "It had no price on the day the trip closed.",
    # 008 regime split
    "INSUFFICIENT_CALIBRATION": "There is not enough earlier history to judge what is normal volatility for this stock.",
    "DEGENERATE_THRESHOLDS": "The low and high volatility limits came out equal, so no regime can be assigned.",
    "AMBIGUOUS_ISIN": "This trip's trades carry conflicting ISINs, so it is listed but not assigned to a regime.",
}
_PREFIX_TEXT = (
    ("no market-data series", "No price history could be fetched for this listing."),
    ("known corporate action inside the review window", "A split, bonus or dividend in the review window would distort its prices."),
    ("not covered by the corporate-action review register", "Splits, bonuses and dividends have not been reviewed for this listing."),
    ("all traded listings are excluded", "Every listing you traded was left out of this comparison."),
    ("not computed: listing excluded", "No return is shown because this listing was left out of the comparison."),
    ("not computed: not in the luck test", "No return is shown because this trip was not part of the luck test."),
    ("no regime label for this trip", "No volatility regime could be worked out for this trip."),
    ("no reference listing", "There is no listing yet to check the latest price date against."),
    ("no bars for", "No recent prices could be found to date the latest bar."),
    ("no known fees", "No fees are known for these trades, or fees do not apply here."),
    ("actual return not available", "The return could not be worked out."),
    ("no exit bar", "No price was available on the trip's closing date."),
    ("insufficient history", "Not enough price history."),
    ("no round trip", "There is no closed trip yet."),
    ("not computed", "This was not computed."),
    ("not available", "This is not available."),
)


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def reason_text(reason: str) -> str:
    """A plain-English sentence for a reason: a code such as NO_MEMBERSHIP, or the analysis' own short text. Never an enum code."""
    if reason.startswith("listing excluded: "):
        return reason_text(reason.removeprefix("listing excluded: "))
    m = _CODE.match(reason)
    if m:
        code, detail = m.group(1), m.group(2) or ""
        counts = _TRIPS_DETAIL.search(detail)
        if code == "INSUFFICIENT_TRIPS":
            return (f"Not enough closed trips for an interval yet: {counts.group(1)} trips · {counts.group(2)} needed."
                    if counts else "Not enough closed trips for an interval yet.")
        if code == "INSUFFICIENT_TRIPS_IN_REGIME":
            return (f"Not enough trips in this regime yet: {counts.group(1)} trips · {counts.group(2)} needed."
                    if counts else "Not enough trips in this regime yet.")
        if code in _CODE_TEXT:
            return _CODE_TEXT[code]
        return _sentence(code.replace("_", " ").lower() + (f": {detail}" if detail else ""))
    low = reason.lower()
    for prefix, text in _PREFIX_TEXT:
        if low.startswith(prefix):
            return text
    return _sentence(reason)


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
        why = reason or "not available"
        return {"value": None, "display": UNAVAILABLE, "unavailable_reason": why, "reason_text": reason_text(why)}
    d = Decimal(value)
    if not d.is_finite():
        raise ValueError("a displayed number must be finite")
    text = format(d, "f") if isinstance(value, Decimal) else value
    if kind.startswith("inr"):
        shown = format_inr(d)
    elif kind == "price":
        shown = format_price(d)
    elif kind == "percentile":
        shown = format_percentile(d)
    elif kind.startswith("ratio"):
        shown = format_percent(d)
    else:
        shown = format_plain(d)
    return {"value": text, "display": shown + _NOTES.get(kind, ""), "unavailable_reason": None, "reason_text": None}
