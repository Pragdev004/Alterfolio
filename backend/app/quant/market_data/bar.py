"""MarketBar: one validated daily bar. Invalid bars are rejected at construction, never repaired (lineage P5)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT

PRICE_FIELDS = ("open", "high", "low", "close", "adjusted_close")


def _check_price(name: str, value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if not (0 < value < MAX_AMOUNT):
        raise ValueError(f"{name} must be above 0 and below {MAX_AMOUNT}")
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise ValueError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")


@dataclass(frozen=True)
class MarketBar:
    """`timestamp` is the provider bar timestamp (aware UTC, any time of day); `session_date` is its exchange-local date.

    `close` and `adjusted_close` are both explicit and provider-defined; there is deliberately no `price` accessor, so no
    price basis is chosen here. Values are the provider-reported numbers exactly as given.
    """

    timestamp: datetime
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be timezone-aware UTC")
        if isinstance(self.session_date, datetime) or not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        for name in PRICE_FIELDS:
            _check_price(name, getattr(self, name))
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, close and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be at most open, close and high")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TypeError("volume must be an int")
        if self.volume < 0:
            raise ValueError("volume must not be negative")  # zero volume is valid
