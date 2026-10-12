"""Yahoo adapter behind the market-data port. The only module that knows Yahoo's URL, suffixes and JSON shape.

Uses Yahoo's unofficial public chart endpoint (it may change or throttle; failures surface as QuoteFailure, never as
a price). Numbers are parsed straight to Decimal (json parse_float=Decimal), so no float ever exists.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT
from app.providers.market.history_port import BarFailure, BarFailureKind, BarOutcome, RawBar, RawBarBatch
from app.providers.market.port import MarketQuote, QuoteFailure, QuoteFailureKind, QuoteOutcome

SOURCE = "yahoo"
MAX_INSTRUMENTS = 200
EXCHANGE_GMT_OFFSET_SECONDS = 19800  # NSE/BSE (IST); checked on every daily-bar response and used to build the request
MAX_BAR_SPAN_DAYS = 3660
MAX_BARS = 6000
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


def _bar_fail(kind: BarFailureKind, detail: str) -> BarFailure:
    return BarFailure(kind, detail)


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite JSON constant {name}")  # NaN/Infinity would otherwise become a float


def _decimal_price(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise ValueError("price is not a JSON number")
    if not value.is_finite() or not (0 < value < MAX_AMOUNT):
        raise ValueError("price outside the accepted range")
    if not (MIN_INPUT_EXPONENT <= value.as_tuple().exponent <= MAX_INPUT_EXPONENT):
        raise ValueError("price exponent outside the accepted range")
    return value


def _integral(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} is not a JSON number")
    if abs(value) >= MAX_AMOUNT or value != value.to_integral_value():
        raise ValueError(f"{what} is not an integer in range")
    return int(value)


def _column(container: dict, key: str, length: int) -> list:
    column = container[key]
    if not isinstance(column, list) or len(column) != length:
        raise ValueError(f"{key} is not an array of {length} values")
    return column


def _parse_bars(instrument: Instrument, body: bytes, retrieved_at: datetime) -> BarOutcome:
    offset = timedelta(seconds=EXCHANGE_GMT_OFFSET_SECONDS)
    try:
        doc = json.loads(body, parse_float=Decimal, parse_int=Decimal, parse_constant=_reject_constant)
        chart = doc["chart"]
        result = chart.get("result")
        if not result:
            error = chart.get("error") or {}
            if str(error.get("code", "")).lower() == "not found":
                return _bar_fail(BarFailureKind.NOT_FOUND, "provider has no such symbol")
            return _bar_fail(BarFailureKind.INVALID_RESPONSE, "no result in provider response")
        first = result[0]
        meta = first["meta"]
        if meta.get("currency") != Currency.INR.value:
            return _bar_fail(BarFailureKind.INVALID_RESPONSE, "bar currency is not INR")
        gmt_offset = meta.get("gmtoffset")
        if isinstance(gmt_offset, bool) or not isinstance(gmt_offset, Decimal) or gmt_offset != EXCHANGE_GMT_OFFSET_SECONDS:
            return _bar_fail(BarFailureKind.INVALID_RESPONSE, "exchange offset is not the expected one")
        stamps = first.get("timestamp")
        if stamps is None:  # a valid answer with no rows at all
            return RawBarBatch(instrument, (), Currency.INR, SOURCE, retrieved_at, offset, 0, 0)
        if not isinstance(stamps, list):
            return _bar_fail(BarFailureKind.INVALID_RESPONSE, "timestamp is not an array")
        n = len(stamps)
        quote = first["indicators"]["quote"][0]
        columns = [_column(quote, k, n) for k in ("open", "high", "low", "close", "volume")]
        columns.append(_column(first["indicators"]["adjclose"][0], "adjclose", n))
        bars: list[RawBar] = []
        empty = 0
        for i in range(n):
            cells = [column[i] for column in columns]
            stamp = stamps[i]
            if isinstance(stamp, bool) or not isinstance(stamp, Decimal) or stamp != stamp.to_integral_value():
                raise ValueError("timestamp is not an integer")
            moment = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
            if all(cell is None for cell in cells):
                empty += 1  # excluded and counted; never filled, never zero
                continue
            if any(cell is None for cell in cells):
                raise ValueError("a row is partially null")
            o, h, low, c, volume, adjusted = cells
            session = (moment + offset).date()
            if bars and not (bars[-1].timestamp < moment and bars[-1].session_date < session):
                raise ValueError("bars are not strictly increasing with one bar per session date")
            bars.append(
                RawBar(
                    timestamp=moment,
                    session_date=session,
                    open=_decimal_price(o),
                    high=_decimal_price(h),
                    low=_decimal_price(low),
                    close=_decimal_price(c),
                    adjusted_close=_decimal_price(adjusted),
                    volume=_integral_volume(volume),
                )
            )
            if len(bars) > MAX_BARS:
                raise ValueError("too many bars")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, ArithmeticError, OverflowError, OSError,
            RecursionError):
        return _bar_fail(BarFailureKind.INVALID_RESPONSE, "unusable provider response")
    return RawBarBatch(instrument, tuple(bars), Currency.INR, SOURCE, retrieved_at, offset, n, empty)


def _integral_volume(value: object) -> int:
    number = _integral(value, "volume")
    if number < 0:
        raise ValueError("volume is negative")
    return number


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

    def get_daily_bars(self, instrument: Instrument, start: date, end: date, retrieved_at: datetime) -> BarOutcome:
        """Daily bars over the inclusive exchange-local session-date range [start, end] (Feature 004 plan, section 4)."""
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        for name, value in (("start", start), ("end", end)):
            if isinstance(value, datetime) or not isinstance(value, date):
                raise ValueError(f"{name} must be a date")
        if start > end:
            raise ValueError("start must not be after end")
        if (end - start).days > MAX_BAR_SPAN_DAYS:
            raise ValueError(f"the range spans more than {MAX_BAR_SPAN_DAYS} days")
        symbol = yahoo_symbol(instrument)
        if symbol is None:
            return _bar_fail(BarFailureKind.NOT_FOUND, "symbol cannot be mapped to the provider")
        offset = timedelta(seconds=EXCHANGE_GMT_OFFSET_SECONDS)

        def local_midnight_epoch(day: date) -> int:
            return int((datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - offset).timestamp())

        # Exactly these parameters. No `events=` (F6): dividends/splits are not requested.
        params = {
            "interval": "1d",
            "period1": str(local_midnight_epoch(start)),
            "period2": str(local_midnight_epoch(end + timedelta(days=1))),
            "includeAdjustedClose": "true",
        }
        try:
            response = self._http().get(_BASE_URL + symbol, params=params)
        except httpx.TimeoutException:
            return _bar_fail(BarFailureKind.PROVIDER_ERROR, "timeout")
        except httpx.HTTPError:
            return _bar_fail(BarFailureKind.PROVIDER_ERROR, "network error")
        if response.status_code == 404:
            return _bar_fail(BarFailureKind.NOT_FOUND, "provider has no such symbol")
        if response.status_code != 200:
            return _bar_fail(BarFailureKind.PROVIDER_ERROR, f"provider returned HTTP {response.status_code}")
        return _parse_bars(instrument, response.content, retrieved_at)

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
