"""Historical daily-bar port: the provider-neutral surface the services may import (Feature 004).

Stdlib + domain only. Everything crossing this port is normalized: a provider adapter converts its own response shapes,
field names and metadata into these types before returning, so no vendor name or vendor payload appears here.

Semantics (identical for every provider):
- `RawBar.timestamp` is the provider's bar timestamp as an aware UTC instant, preserved exactly. It is not assumed to be a
  session open or close.
- `RawBar.session_date` is the exchange-local calendar date of that timestamp, derived by the adapter.
- Prices are the provider-reported numbers as exact Decimals (no rounding, no float). `close` and `adjusted_close` are
  both explicit; their adjustment semantics are provider-defined.
- `RawBarBatch.exchange_utc_offset` is the only exchange-time information that crosses the port.
- A valid batch may hold less history than requested; nothing here asserts that the requested range was covered.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable

from app.domain.enums import Currency
from app.domain.instrument import Instrument


class BarFailureKind(str, Enum):
    NOT_FOUND = "NOT_FOUND"  # the provider answered: it has no such listing
    PROVIDER_ERROR = "PROVIDER_ERROR"  # the provider could not be asked or did not answer (timeout, throttling, outage)
    INVALID_RESPONSE = "INVALID_RESPONSE"  # an answer arrived but is unusable (shape, currency, values)


@dataclass(frozen=True)
class BarFailure:
    kind: BarFailureKind
    detail: str


@dataclass(frozen=True)
class RawBar:
    timestamp: datetime
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int


@dataclass(frozen=True)
class RawBarBatch:
    instrument: Instrument
    bars: tuple[RawBar, ...]  # provider order; rows with no data at all are excluded and counted, never filled
    currency: Currency
    source: str  # opaque provider identifier
    retrieved_at: datetime  # when the request was made (injected clock), aware UTC
    exchange_utc_offset: timedelta  # exchange-local offset from UTC
    rows_returned: int  # provider rows including the empty ones
    empty_rows_excluded: int  # rows with no data in any field


BarOutcome = RawBarBatch | BarFailure


@runtime_checkable
class HistoricalBarProvider(Protocol):
    def get_daily_bars(
        self, instrument: Instrument, start: date, end: date, retrieved_at: datetime
    ) -> BarOutcome:
        """Daily bars for one listing over the inclusive exchange-local session-date range [start, end].

        Must not raise for provider, network or response-shape problems: return a BarFailure. A programming error
        (naive `retrieved_at`, `start > end`) may raise ValueError.
        """
        ...
