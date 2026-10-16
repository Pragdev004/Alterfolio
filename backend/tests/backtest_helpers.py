"""Shared builders and test-only strategies for the Feature 005 engine tests (synthetic symbols and prices)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.quant.backtest.config import BacktestConfig, StrategyIdentity, Unavailable
from app.quant.market_data.series import MarketSeries
from tests.market_helpers import IST_OFFSET, mk_bar, mk_provenance

A = Instrument("AAA", Exchange.NSE)
B = Instrument("BBB", Exchange.NSE)
RETRIEVED = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
MON = date(2026, 3, 2)
WEEK = [MON + timedelta(days=i) for i in range(5)]  # Mon..Fri 2026-03-02..06
# (open, close) per session for the hand-computed scenarios
PRICES = {
    WEEK[0]: ("100", "102"),
    WEEK[1]: ("104", "106"),
    WEEK[2]: ("105", "110"),
    WEEK[3]: ("108", "107"),
    WEEK[4]: ("109", "111"),
}


def bar(d, open_, close):
    o, c = D(open_), D(close)
    return mk_bar(d, open=o, close=c, high=max(o, c) + 1, low=min(o, c) - 1, adjusted_close=c)


def make_series(instrument=A, prices=PRICES, retrieved_at=RETRIEVED):
    dates = sorted(prices)
    return MarketSeries.from_eligible_bars(
        instrument=instrument,
        currency=Currency.INR,
        bars=tuple(bar(d, *prices[d]) for d in dates),
        exchange_utc_offset=IST_OFFSET,
        provenance=mk_provenance(dates, retrieved_at),
    )


def config(cash="10000", start=WEEK[0], end=WEEK[-1]):
    return BacktestConfig(start_date=start, end_date=end, initial_cash=D(cash), currency=Currency.INR)


class Scripted:
    """Returns `plan[session]` (a mapping or Unavailable); sessions not in the plan get an empty mapping (no change)."""

    def __init__(self, plan, version="1", **params):
        self.identity = StrategyIdentity.create("scripted", version, params)
        self.plan, self.views = plan, []

    def decide(self, view):
        self.views.append(view)
        return self.plan.get(view.as_of, {})


class AlwaysUnavailable:
    identity = StrategyIdentity("never", "1")

    def decide(self, view):
        return Unavailable("not enough history")
