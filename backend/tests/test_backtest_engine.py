"""Backtest engine: hand-computed scenarios, timing, leakage and determinism (Feature 005 step 5)."""

from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.domain.enums import TradeSide
from app.quant.backtest.config import BacktestInputError, Unavailable
from app.quant.backtest.engine import StrategyView, run_backtest
from app.quant.backtest.execution import INSUFFICIENT_CASH, UNFILLED_END_OF_DATA
from tests.backtest_helpers import A, B, PRICES, WEEK, AlwaysUnavailable, Scripted, config, make_series

D1, D2, D3, D4, D5 = WEEK


def equity(result):
    return [str(p.equity) for p in result.equity_curve]


def test_buy_and_hold_matches_the_hand_computed_scenario_to_the_last_digit():
    result = run_backtest([make_series()], config(), Scripted({D1: {A: D(10)}}))
    assert equity(result) == ["10000", "10020", "10060", "10030", "10070"]
    (fill,) = result.fills
    assert (fill.date, fill.price, fill.notional, fill.order_id) == (D2, D("104"), D("1040"), 1)
    assert result.final_cash == D("8960") and result.final_positions == ((A, D(10)),)
    assert result.rejections == () and result.decisions_unavailable == ()


def test_rebalance_scenario_with_sell_buy_and_an_unfilled_final_order():
    plan = {D1: {A: D(10)}, D2: {A: D(0)}, D3: {A: D(5)}, D5: {A: D(20)}}
    result = run_backtest([make_series()], config(), Scripted(plan))
    assert equity(result) == ["10000", "10020", "10010", "10005", "10025"]
    assert [(f.date, f.side, f.quantity, f.price) for f in result.fills] == [
        (D2, TradeSide.BUY, D(10), D("104")),
        (D3, TradeSide.SELL, D(10), D("105")),
        (D4, TradeSide.BUY, D(5), D("108")),
    ]
    assert [(o.order_id, o.decided_on, o.side, o.quantity) for o in result.orders] == [
        (1, D1, TradeSide.BUY, D(10)),
        (2, D2, TradeSide.SELL, D(10)),
        (3, D3, TradeSide.BUY, D(5)),
        (4, D5, TradeSide.BUY, D(15)),
    ]
    assert [(r.order_id, r.date, r.reason) for r in result.rejections] == [(4, D5, UNFILLED_END_OF_DATA)]
    assert result.final_cash == D("9470") and result.final_positions == ((A, D(5)),)


def test_an_order_never_fills_on_its_decision_date():
    result = run_backtest([make_series()], config(), Scripted({D1: {A: D(1)}}))
    assert result.fills[0].date > result.orders[0].decided_on and result.equity_curve[0].positions_value == 0


def test_unaffordable_buy_is_rejected_whole_and_cash_stays_intact():
    result = run_backtest([make_series()], config(cash="500"), Scripted({D1: {A: D(10)}}))
    assert result.fills == () and [r.reason for r in result.rejections] == [INSUFFICIENT_CASH]
    assert set(equity(result)) == {"500"} and result.final_positions == ()


def test_sells_execute_before_buys_so_a_switch_is_funded():
    prices_b = {d: ("50", "50") for d in WEEK}
    plan = {D1: {A: D(90)}, D2: {A: D(0), B: D(20)}}
    result = run_backtest([make_series(A), make_series(B, prices_b)], config("10000"), Scripted(plan))
    # D2 fill: A 90 @104 = 9360 -> cash 640; D3: sell 90 @105 = 9450 (cash 10090) THEN buy 20 B @50 = 1000
    assert [(f.instrument, f.side) for f in result.fills] == [(A, TradeSide.BUY), (A, TradeSide.SELL), (B, TradeSide.BUY)]
    assert result.final_cash == D("9090") and result.rejections == ()


def test_unavailable_decision_holds_positions_creates_no_orders_and_keeps_queued_orders():
    class Flaky(Scripted):
        def decide(self, view):
            return Unavailable("warming up") if view.as_of == D2 else super().decide(view)

    result = run_backtest([make_series()], config(), Flaky({D1: {A: D(10)}, D3: {A: D(0)}}))
    assert result.decisions_unavailable == ((D2, "warming up"),)
    assert [f.date for f in result.fills] == [D2, D4]  # the D1 order still settled on D2; D3's sell settles on D4
    assert len(result.orders) == 2


def test_always_unavailable_records_every_date_and_never_trades():
    result = run_backtest([make_series()], config(), AlwaysUnavailable())
    assert len(result.decisions_unavailable) == 5 and result.orders == () and set(equity(result)) == {"10000"}


def test_empty_calendar_is_unavailable():
    series = [make_series(A, {D1: PRICES[D1]}), make_series(B, {D2: PRICES[D2]})]
    assert isinstance(run_backtest(series, config(), AlwaysUnavailable()), Unavailable)


def test_warmup_history_is_visible_but_never_traded():
    prices = {date(2026, 2, 27): ("90", "91"), **PRICES}
    seen = Scripted({})
    result = run_backtest([make_series(prices=prices)], config(start=D2), seen)
    assert result.calendar_dates[0] == D2 and result.orders == ()
    assert seen.views[0].as_of == D2 and seen.views[0].series[A].first_session_date == date(2026, 2, 27)


def test_inner_join_drops_missing_dates_and_the_fill_goes_to_the_next_common_date():
    prices_b = {d: p for d, p in PRICES.items() if d != D2}
    result = run_backtest([make_series(A), make_series(B, prices_b)], config(), Scripted({D1: {A: D(10)}}))
    assert result.dropped_dates == (D2,) and D2 not in result.calendar_dates
    assert result.fills[0].date == D3 and result.fills[0].price == D("105")


def test_peeking_strategy_never_sees_a_session_after_its_decision_date():
    class Peek(Scripted):
        def decide(self, view):
            assert view.series[A].last_session_date == view.as_of
            assert view.series[A].bars[-1].session_date == view.as_of
            return super().decide(view)

    run_backtest([make_series()], config(), Peek({}))


def test_changing_only_the_next_open_changes_the_fill_not_the_decision():
    changed = {**PRICES, D2: ("999", "106")}
    s1, s2 = Scripted({D1: {A: D(1)}}), Scripted({D1: {A: D(1)}})
    base = run_backtest([make_series()], config(), s1)
    other = run_backtest([make_series(prices=changed)], config(), s2)
    assert base.orders == other.orders and base.fills[0].price != other.fills[0].price
    assert s1.views[0].series[A].bars == s2.views[0].series[A].bars


def test_perturbing_bars_after_t_plus_one_leaves_earlier_results_unchanged():
    wild = {d: ("7", "8") if d > D3 else p for d, p in PRICES.items()}
    base = run_backtest([make_series()], config(), Scripted({D1: {A: D(10)}}))
    other = run_backtest([make_series(prices=wild)], config(), Scripted({D1: {A: D(10)}}))
    assert base.equity_curve[:3] == other.equity_curve[:3] and base.fills == other.fills


def test_runs_are_repeatable_and_input_order_does_not_matter():
    prices_b = {d: ("50", "51") for d in WEEK}
    plan = {D1: {A: D(3), B: D(4)}, D3: {A: D(1)}}
    one = run_backtest([make_series(A), make_series(B, prices_b)], config(), Scripted(plan))
    two = run_backtest([make_series(B, prices_b), make_series(A)], config(), Scripted(plan))
    assert one.to_dict() == two.to_dict() and one.fingerprint == two.fingerprint


def test_strategy_view_is_read_only_and_a_returned_mapping_is_copied():
    returned = {A: D(2)}

    class Evil(Scripted):
        def decide(self, view):
            with pytest.raises(TypeError):
                view.positions[A] = D(99)  # type: ignore[index]
            with pytest.raises(TypeError):
                view.series[A] = None  # type: ignore[index]
            return returned

    result = run_backtest([make_series()], config(), Evil({}))
    returned[A] = D(999)  # mutating after the run changes nothing
    assert result.orders[0].quantity == D(2)


@pytest.mark.parametrize(
    "bad", [{A: D("-1")}, {A: D("1.5")}, {A: 1.0}, {A: True}, {A: D("NaN")}, {B: D(1)}, {A: "3"}, ["x"]]
)
def test_invalid_targets_raise(bad):
    with pytest.raises(BacktestInputError):
        run_backtest([make_series()], config(), Scripted({D1: bad}))


def test_integral_targets_in_other_forms_are_normalized_and_int_is_accepted():
    result = run_backtest([make_series()], config(), Scripted({D1: {A: D("3.0")}, D2: {A: 3}}))
    assert result.orders[0].quantity == D(3) and len(result.orders) == 1


def test_defective_run_inputs_raise():
    with pytest.raises(BacktestInputError):
        run_backtest([make_series()], "cfg", Scripted({}))  # type: ignore[arg-type]
    with pytest.raises(BacktestInputError):
        run_backtest([make_series()], config(), object())  # type: ignore[arg-type]
    short = make_series(
        retrieved_at=datetime(2026, 3, 5, 10, 0, tzinfo=timezone.utc), prices={d: PRICES[d] for d in (D1, D2, D3)}
    )
    with pytest.raises(BacktestInputError):
        run_backtest([short], config(), Scripted({}))  # observed_through 03-04 < end_date 03-06


def test_strategy_view_copies_mappings_it_is_given():
    source = {A: D(1)}
    view = StrategyView(D1, {}, D(1), source)
    source[A] = D(5)
    assert view.positions[A] == D(1)
