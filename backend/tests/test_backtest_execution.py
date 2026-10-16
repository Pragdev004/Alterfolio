"""Backtest execution model (Feature 005 step 4)."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.enums import Exchange, TradeSide
from app.domain.instrument import Instrument
from app.quant.backtest.config import BacktestInputError
from app.quant.backtest.execution import (
    INSUFFICIENT_CASH, INSUFFICIENT_POSITION, Fill, NextOpenExecution, Order, Rejection, apply_fill)
from app.quant.backtest.portfolio import Portfolio
from tests.market_helpers import mk_bar

A = Instrument("AAA", Exchange.NSE)
DAY = date(2026, 3, 3)
BAR = mk_bar(DAY, open=D("100.25"), high=D("120"), low=D("90"), close=D("111"), adjusted_close=D("55"))


def order(side, qty, oid=1):
    return Order(oid, date(2026, 3, 2), A, side, D(qty))


def test_buy_fills_at_the_bar_open_never_close_or_adjusted_close():
    portfolio = Portfolio.initial(D("1000"))
    fill = NextOpenExecution().fill(order(TradeSide.BUY, 4), BAR, portfolio)
    assert fill == Fill(1, DAY, A, TradeSide.BUY, D(4), D("100.25"), D("401.00"))
    after = apply_fill(portfolio, fill)
    assert after.cash == D("599.00") and after.quantity(A) == D(4)


def test_sell_fills_at_open_and_credits_the_exact_notional():
    portfolio = Portfolio(cash=D(0), positions=((A, D(3)),))
    fill = NextOpenExecution().fill(order(TradeSide.SELL, 2), BAR, portfolio)
    assert fill.notional == D("200.50") and apply_fill(portfolio, fill).cash == D("200.50")


def test_unaffordable_buy_is_rejected_whole_and_the_portfolio_is_untouched():
    portfolio = Portfolio.initial(D("400.99"))
    result = NextOpenExecution().fill(order(TradeSide.BUY, 4), BAR, portfolio)
    assert result == Rejection(1, DAY, INSUFFICIENT_CASH)
    assert portfolio.cash == D("400.99") and portfolio.positions == ()


def test_exactly_affordable_buy_fills():
    assert isinstance(NextOpenExecution().fill(order(TradeSide.BUY, 4), BAR, Portfolio.initial(D("401.00"))), Fill)


def test_oversell_and_selling_an_unheld_instrument_are_rejected_whole():
    held = Portfolio(cash=D(0), positions=((A, D(1)),))
    assert NextOpenExecution().fill(order(TradeSide.SELL, 2), BAR, held) == Rejection(1, DAY, INSUFFICIENT_POSITION)
    assert NextOpenExecution().fill(order(TradeSide.SELL, 1), BAR, Portfolio.initial(D(5))).reason == INSUFFICIENT_POSITION


def test_other_errors_are_not_swallowed():
    huge = mk_bar(DAY, open=D("9" * 15), high=D("9" * 15), close=D("9" * 15), adjusted_close=D("9" * 15))
    # price 999999999999999 x 2 exceeds MAX_AMOUNT: a bound violation (BacktestInputError), not a business rejection
    with pytest.raises(BacktestInputError):
        NextOpenExecution().fill(order(TradeSide.BUY, 2), huge, Portfolio.initial(D("999999999999999")))


def test_execution_is_deterministic_and_never_reads_adjusted_close():
    p = Portfolio.initial(D("1000"))
    one = NextOpenExecution().fill(order(TradeSide.BUY, 1), BAR, p)
    other_bar = mk_bar(DAY, open=D("100.25"), high=D("120"), low=D("90"), close=D("111"), adjusted_close=D("1"))
    assert NextOpenExecution().fill(order(TradeSide.BUY, 1), other_bar, p) == one


@pytest.mark.parametrize("kwargs", [dict(order_id=0), dict(order_id=True), dict(side="BUY"), dict(quantity=D("1.5")), dict(quantity=D(0))])
def test_order_rejects_malformed_fields(kwargs):
    fields = dict(order_id=1, decided_on=DAY, instrument=A, side=TradeSide.BUY, quantity=D(1))
    fields.update(kwargs)
    with pytest.raises((ValueError, BacktestInputError)):
        Order(**fields)


def test_rejection_reason_must_be_known():
    with pytest.raises(ValueError):
        Rejection(1, DAY, "BECAUSE")
