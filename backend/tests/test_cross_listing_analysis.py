"""Real-data bug: one ISIN bought on NSE and BSE and sold on BSE is ONE round trip (analysis keys on ISIN, not listing)."""
from datetime import date, timedelta

from analysis_helpers import TRADED, TRADED_ISIN, FakeBars, add_trade, config
from conftest import USER_A
from test_portfolio_analysis import by_name, make

from app.domain.enums import Exchange, TradeSide
from app.domain.instrument import Instrument

BSE = Instrument(TRADED.symbol, Exchange.BSE)


def seed(session, n=14):
    for k in range(n):
        d = date(2026, 3, 2) + timedelta(days=k * 8)
        add_trade(session, USER_A, TradeSide.BUY, d, qty="10")
        add_trade(session, USER_A, TradeSide.BUY, d + timedelta(days=1), qty="10", instrument=BSE)
        add_trade(session, USER_A, TradeSide.SELL, d + timedelta(days=3), qty="20", instrument=BSE)
    session.commit()


def test_cross_listing_sell_closes_one_trip_per_isin_not_an_oversell(session):
    seed(session)
    facts = make(session).analyse(USER_A, date(2026, 9, 30))
    named = by_name(facts)
    assert not any(name == "006" for name, _ in facts.unavailable)  # no BiasInputError oversell
    assert named["luck.coverage.trips_total"].value == "14"
    assert named["luck.coverage.trips_analysed"].value == "14"

