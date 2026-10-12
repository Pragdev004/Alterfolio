"""Yahoo adapter behind the market-data port. The only module that knows Yahoo's URL, suffixes and JSON shape.

Uses Yahoo's unofficial public chart endpoint (it may change or throttle; failures surface as QuoteFailure, never as
a price). Numbers are parsed straight to Decimal (json parse_float=Decimal), so no float ever exists.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.domain.numeric import MAX_AMOUNT
from app.providers.market.port import MarketQuote, QuoteFailure, QuoteFailureKind, QuoteOutcome

SOURCE = "yahoo"
MAX_INSTRUMENTS = 200
_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
_SUFFIX = {Exchange.NSE: ".NS", Exchange.BSE: ".BO"}
_SYMBOL = re.compile(r"^[A-Z0-9&_-]{1,64}$")


def yahoo_symbol(instrument: Instrument) -> str | None:
    """Trim + upper-case, then accept only a conservative character set; anything else is not looked up."""
    base = instrument.symbol.strip().upper()
    if not _SYMBOL.fullmatch(base):
        return None
    return base + _SUFFIX[instrument.exchange]


def _fail(kind: QuoteFailureKind, detail: str) -> QuoteFailure:
    return QuoteFailure(kind, detail)


def _parse(instrument: Instrument, body: bytes, retrieved_at: datetime) -> QuoteOutcome:
    try:
        doc = json.loads(body, parse_float=Decimal)
        chart = doc["chart"]
        result = chart.get("result")
        if not result:
            error = chart.get("error") or {}
            if str(error.get("code", "")).lower() == "not found":
                return _fail(QuoteFailureKind.NOT_FOUND, "provider has no such symbol")
            return _fail(QuoteFailureKind.INVALID_RESPONSE, "no result in provider response")
        meta = result[0]["meta"]
        price = meta.get("regularMarketPrice")
        stamp = meta.get("regularMarketTime")
        currency = meta.get("currency")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "unparseable provider response")

    if isinstance(price, bool) or not isinstance(price, (Decimal, int)):
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "missing or non-numeric price")
    price = Decimal(price)
    if not price.is_finite() or price <= 0 or price >= MAX_AMOUNT:
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "price outside the accepted range")
    if currency != Currency.INR.value:
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "quote currency is not INR")
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "missing or invalid quote time")
    try:
        price_timestamp = datetime.fromtimestamp(stamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _fail(QuoteFailureKind.INVALID_RESPONSE, "quote time out of range")
    return MarketQuote(
        instrument=instrument,
        price=price,
        currency=Currency.INR,
        price_timestamp=price_timestamp,
        retrieved_at=retrieved_at,
        source=SOURCE,
    )


class YahooProvider:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 3,
        total_budget_seconds: float = 20,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds
        self._budget = total_budget_seconds
        self._monotonic = monotonic

    def _http(self) -> httpx.Client:
        if self._client is None:  # built lazily: constructing the app must not touch the network
            self._client = httpx.Client(timeout=self._timeout, headers={"User-Agent": "Mozilla/5.0 alterfolio"})
        return self._client

    def get_quotes(
        self, instruments: Sequence[Instrument], retrieved_at: datetime
    ) -> dict[Instrument, QuoteOutcome]:
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        distinct = list(dict.fromkeys(instruments))
        out: dict[Instrument, QuoteOutcome] = {}
        started = self._monotonic()
        for index, instrument in enumerate(distinct):
            if index >= MAX_INSTRUMENTS:
                out[instrument] = _fail(QuoteFailureKind.PROVIDER_ERROR, "too many instruments in one request")
                continue
            symbol = yahoo_symbol(instrument)
            if symbol is None:
                out[instrument] = _fail(QuoteFailureKind.NOT_FOUND, "symbol cannot be mapped to the provider")
                continue
            if self._monotonic() - started >= self._budget:
                out[instrument] = _fail(QuoteFailureKind.PROVIDER_ERROR, "timeout: provider time budget exhausted")
                continue
            out[instrument] = self._one(instrument, symbol, retrieved_at)
        return out

    def _one(self, instrument: Instrument, symbol: str, retrieved_at: datetime) -> QuoteOutcome:
        try:
            response = self._http().get(_BASE_URL + symbol, params={"range": "1d", "interval": "1d"})
        except httpx.TimeoutException:
            return _fail(QuoteFailureKind.PROVIDER_ERROR, "timeout")
        except httpx.HTTPError:
            return _fail(QuoteFailureKind.PROVIDER_ERROR, "network error")
        if response.status_code == 404:
            return _parse(instrument, response.content, retrieved_at)
        if response.status_code != 200:
            return _fail(QuoteFailureKind.PROVIDER_ERROR, f"provider returned HTTP {response.status_code}")
        return _parse(instrument, response.content, retrieved_at)
