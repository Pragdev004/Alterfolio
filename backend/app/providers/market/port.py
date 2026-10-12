"""Market-data port: the only provider-facing surface the services may import (FR-9).

Stdlib + domain only. A provider supplies observations; it never owns portfolio accounting. Provider response
shapes stop at the adapter: everything crossing this port is a MarketQuote or a QuoteFailure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from app.domain.enums import Currency
from app.domain.instrument import Instrument


class QuoteFailureKind(str, Enum):
    NOT_FOUND = "NOT_FOUND"  # the provider answered: it has no usable quote for this listing
    PROVIDER_ERROR = "PROVIDER_ERROR"  # the provider could not be asked or did not answer (timeout, 429, 5xx, network)
    INVALID_RESPONSE = "INVALID_RESPONSE"  # an answer arrived but is unusable (bad price, currency, time, shape)


@dataclass(frozen=True)
class MarketQuote:
    """One market observation for one listing. Valuation price = last traded price (a closed market is not an error)."""

    instrument: Instrument
    price: Decimal
    currency: Currency
    price_timestamp: datetime  # provider's last-trade time, tz-aware UTC
    retrieved_at: datetime  # when we asked (injected clock), tz-aware UTC
    source: str


@dataclass(frozen=True)
class QuoteFailure:
    kind: QuoteFailureKind
    detail: str


QuoteOutcome = MarketQuote | QuoteFailure


class MarketDataProvider(Protocol):
    def get_quotes(
        self, instruments: Sequence[Instrument], retrieved_at: datetime
    ) -> dict[Instrument, QuoteOutcome]:
        """Return one outcome per requested instrument. Must not raise for per-instrument or provider problems."""
        ...
