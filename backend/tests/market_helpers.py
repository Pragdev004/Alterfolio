"""Shared builders for the Feature 004 market-data tests (synthetic symbols and prices only)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.quant.market_data.bar import MarketBar
from app.quant.market_data.provenance import DataProvenance
from app.quant.market_data.series import MarketSeries

IST_OFFSET = timedelta(hours=5, minutes=30)
INSTRUMENT = Instrument("ZZTEST", Exchange.NSE)
RETRIEVED = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)  # local date 2026-03-10 (15:30 IST)
REQUEST_START = date(2026, 1, 1)
REQUEST_END = date(2026, 3, 10)


def ts_for(d: date, hour: int = 3, minute: int = 45) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def mk_bar(d: date, **overrides) -> MarketBar:
    fields = dict(
        timestamp=ts_for(d),
        session_date=d,
        open=D("100"),
        high=D("110"),
        low=D("90"),
        close=D("105"),
        adjusted_close=D("104.5"),
        volume=1000,
    )
    fields.update(overrides)
    return MarketBar(**fields)


def mk_provenance(dates=(), retrieved_at: datetime = RETRIEVED, **overrides) -> DataProvenance:
    dates = sorted(dates)
    fields = dict(
        source="fake",
        request_start=REQUEST_START,
        request_end=REQUEST_END,
        retrieved_at=retrieved_at,
        rows_returned=len(dates),
        empty_rows_excluded=0,
        ineligible_bars_excluded=0,
        eligible_bars_at_fetch=len(dates),
        first_eligible_session_date_at_fetch=dates[0] if dates else None,
        last_eligible_session_date_at_fetch=dates[-1] if dates else None,
    )
    fields.update(overrides)
    return DataProvenance(**fields)


def mk_series(dates, retrieved_at: datetime = RETRIEVED, bars=None, provenance=None, **bar_overrides) -> MarketSeries:
    dates = sorted(dates)
    bars = tuple(mk_bar(d, **bar_overrides) for d in dates) if bars is None else bars
    return MarketSeries.from_eligible_bars(
        instrument=INSTRUMENT,
        currency=Currency.INR,
        bars=bars,
        exchange_utc_offset=IST_OFFSET,
        provenance=provenance or mk_provenance(dates, retrieved_at),
    )


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]
