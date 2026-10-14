"""Backtest portfolio accounting (Feature 005 step 2): exact Decimal, long-only, whole shares, immutable."""

import dataclasses
from decimal import Context, Decimal as D, Inexact
from types import MappingProxyType

import pytest

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.domain.numeric import EXACT_CONTEXT, MAX_AMOUNT, MONEY_CONTEXT
from app.quant.backtest import portfolio
from app.quant.backtest.config import BacktestInputError
from app.quant.backtest.portfolio import (
    InsufficientCash,
    InsufficientPosition,
    Portfolio,
    PortfolioError,
    Valuation,
)

A = Instrument("AAA", Exchange.NSE)
B = Instrument("BBB", Exchange.NSE)
A_BSE = Instrument("AAA", Exchange.BSE)


def held(cash, *pairs):
    return Portfolio(cash=D(cash), positions=tuple((i, D(q)) for i, q in pairs))


# ---- construction and invariants ------------------------------------------------------------------------------------


def test_initial_portfolio_has_exact_cash_and_no_positions():
    p = Portfolio.initial(D("100000.50"))
    assert p.cash.as_tuple() == D("100000.50").as_tuple()  # no normalization
    assert p.positions == () and dict(p.as_mapping()) == {}
    assert p.quantity(A) == D(0)


def test_error_hierarchy_keeps_bound_violations_as_input_errors():
    assert issubclass(PortfolioError, BacktestInputError)
    assert issubclass(InsufficientCash, PortfolioError) and issubclass(InsufficientPosition, PortfolioError)


@pytest.mark.parametrize("bad", [D("-0.01"), MAX_AMOUNT, MAX_AMOUNT + 1, D("NaN"), D("Infinity"), D("-Infinity"), 5, 5.0, "5", None, True])
def test_cash_must_be_a_finite_decimal_from_zero_up_to_below_max_amount(bad):
    with pytest.raises(PortfolioError):
        Portfolio(cash=bad)


def test_cash_may_be_exactly_zero_and_just_below_max_amount():
    assert Portfolio(cash=D(0)).cash == 0
    assert Portfolio(cash=MAX_AMOUNT - 1).cash == MAX_AMOUNT - 1


@pytest.mark.parametrize("cash", [D("1E-21"), D("1E+14")])
def test_cash_exponent_outside_the_repository_range_is_rejected(cash):
    with pytest.raises(PortfolioError):
        Portfolio(cash=cash)


@pytest.mark.parametrize(
    "positions",
    [
        [(A, D(1))],  # not a tuple
        ((A, D(1)),) + ((A, D(2)),),  # duplicate
        ((B, D(1)), (A, D(1))),  # unsorted
        ((A, D(0)),),  # zero is never stored
        ((A, D(-1)),),
        ((A, D("1.5")),),
        ((A, D("NaN")),),
        ((A, 3),),  # not a Decimal
        ((("AAA", Exchange.NSE), D(1)),),  # a tuple, not an Instrument
        ((A, D(MAX_AMOUNT)),),
        (A,),  # not a pair
        ((A, D("0.0")),),
        ((A, D("-0")),),
        ((A, D("Infinity")),),
        ((A, D("-3")),),
        (("AAA", D(1)),),  # key is text
        ((None, D(1)),),
        ((A, D(1)), (A_BSE, D(1)), (B, D(1))),  # NSE listed before BSE is out of order
        ((A, D(1), D(2)),),  # three-tuple
    ],
)
def test_direct_construction_rejects_non_canonical_positions(positions):
    with pytest.raises(PortfolioError):
        Portfolio(cash=D(1), positions=positions)


@pytest.mark.parametrize(
    "raw, plain",
    [("5.0", 5), ("5.000", 5), ("1E+2", 100), ("12E+1", 120), ("100.00", 100), ("0.5E+1", 5), ("7", 7)],
)
def test_direct_construction_accepts_integral_decimals_and_normalizes_them_exactly(raw, plain):
    p = Portfolio(cash=D(1), positions=((A, D(raw)),))
    stored = p.positions[0][1]
    assert stored == D(plain) and stored.as_tuple() == D(plain).as_tuple()  # plain integer representation
    assert p == Portfolio(cash=D(1), positions=((A, D(plain)),)) and hash(p) == hash(
        Portfolio(cash=D(1), positions=((A, D(plain)),))
    )


@pytest.mark.parametrize("raw", ["5.5", "0.5", "1E-1", "99.999999", "1.0000000000000000001", "0.0000000000000000001"])
def test_fractional_quantities_are_rejected_not_rounded(raw):
    for call in (
        lambda: Portfolio(cash=D(1), positions=((A, D(raw)),)),
        lambda: Portfolio.initial(D(1000)).buy(A, D(raw), D(1)),
        lambda: held("0", (A, 10)).sell(A, D(raw), D(1)),
    ):
        with pytest.raises(PortfolioError):
            call()


@pytest.mark.parametrize("raw", ["-1", "-5.0", "-0", "-0.0", "NaN", "-NaN", "sNaN", "Infinity", "-Infinity"])
def test_negative_and_non_finite_quantities_are_rejected_in_every_path(raw):
    for call in (
        lambda: Portfolio(cash=D(1), positions=((A, D(raw)),)),
        lambda: Portfolio.initial(D(1000)).buy(A, D(raw), D(1)),
        lambda: held("0", (A, 10)).sell(A, D(raw), D(1)),
    ):
        with pytest.raises(PortfolioError):
            call()


def test_integral_decimal_representations_are_equivalent_inputs_for_trades():
    plain = Portfolio.initial(D(1000)).buy(A, D(5), D(2)).sell(A, D(2), D(3))
    odd = Portfolio.initial(D(1000)).buy(A, D("5.00"), D(2)).sell(A, D("0.2E+1"), D(3))
    assert odd == plain and odd.positions[0][1].as_tuple() == D(3).as_tuple()


def test_zero_quantity_positions_are_still_never_stored_even_if_written_as_zero():
    for raw in ("0", "0.0", "0E+3"):
        with pytest.raises(PortfolioError):
            Portfolio(cash=D(1), positions=((A, D(raw)),))
    assert held("0", (A, 3)).sell(A, D("3.0"), D(1)).positions == ()


def test_positions_are_canonically_ordered_by_exchange_then_symbol():
    p = Portfolio.initial(D(10**6)).buy(B, D(1), D(10)).buy(A_BSE, D(1), D(10)).buy(A, D(1), D(10))
    assert [i for i, _ in p.positions] == [A_BSE, A, B]  # (exchange.value, symbol): 'BSE' < 'NSE'


# ---- buy / sell arithmetic ------------------------------------------------------------------------------------------


def test_buy_debits_cash_exactly_and_adds_whole_shares():
    p = Portfolio.initial(D("100000")).buy(A, D(10), D("1234.5"))
    assert p.cash == D("87655.0") and p.quantity(A) == D(10)
    assert p.buy(A, D(5), D("1000")).quantity(A) == D(15)
    assert p.buy(A, D(5), D("1000")).cash == D("82655.0")


def test_sell_credits_cash_exactly_and_reduces_position():
    p = held("1000", (A, 10)).sell(A, D(4), D("1300.25"))
    assert p.cash == D("6201.00") and p.quantity(A) == D(6)


def test_selling_the_whole_position_removes_the_entry():
    p = held("0", (A, 10)).sell(A, D(10), D("2"))
    assert p.positions == () and p.cash == D(20)


def test_operations_return_new_portfolios_and_never_change_the_original():
    p = held("1000", (A, 10))
    after = p.buy(B, D(1), D(5))
    assert after is not p and p.cash == D(1000) and p.positions == ((A, D(10)),)


def test_quantity_with_trailing_zero_exponent_is_stored_as_a_plain_whole_number():
    p = Portfolio.initial(D(1000)).buy(A, D("5.0"), D(2)).buy(B, D("1E+2"), D(1))
    assert dict(p.positions)[A].as_tuple() == D(5).as_tuple()
    assert p.quantity(B) == D(100) and p.cash == D(1000 - 10 - 100)


def test_exact_affordability_boundary_leaves_exactly_zero_cash():
    p = Portfolio.initial(D("1000.00")).buy(A, D(10), D("100"))
    assert p.cash == 0 and p.quantity(A) == D(10)


def test_arithmetic_is_exact_beyond_the_28_digits_money_context_would_round_to():
    price, qty = D("1.23456789012345678901"), D(12345678901)
    cash = D("1000000000000")
    exact = (D(12345678901 * 123456789012345678901)).scaleb(-20, context=Context(prec=100))
    assert MONEY_CONTEXT.multiply(qty, price) != exact  # the narrow context rounds; the portfolio must not
    p = Portfolio.initial(cash).buy(A, qty, price)
    expected_cash = D(10**12 * 10**20 - 12345678901 * 123456789012345678901).scaleb(-20, context=Context(prec=100))
    assert expected_cash == D("984758421247.05075323473403432199")  # 32 significant digits, no rounding
    assert p.cash == expected_cash and p.cash.as_tuple().exponent == -20
    assert p.sell(A, qty, price).cash == cash  # round trip returns the exact original


# ---- rejections -----------------------------------------------------------------------------------------------------


def test_unaffordable_buy_is_rejected_in_full():
    p = Portfolio.initial(D("1000"))
    with pytest.raises(InsufficientCash):
        p.buy(A, D(10), D("100.01"))  # notional 1000.10
    assert p.cash == D(1000) and p.positions == ()


def test_oversell_and_selling_an_unheld_instrument_are_rejected():
    p = held("0", (A, 5))
    with pytest.raises(InsufficientPosition):
        p.sell(A, D(6), D(1))
    with pytest.raises(InsufficientPosition):
        p.sell(B, D(1), D(1))
    with pytest.raises(InsufficientPosition):
        p.sell(A_BSE, D(1), D(1))  # the other listing is a different instrument


@pytest.mark.parametrize(
    "qty",
    [D("1.5"), D("0.5"), D(0), D(-1), D("-0"), D("NaN"), D("Infinity"), MAX_AMOUNT, MAX_AMOUNT + 1, D("1E-21"), 3, 3.0, "3", None, True],
)
def test_invalid_quantities_are_rejected_for_buy_and_sell(qty):
    p = held("1000000", (A, 10))
    with pytest.raises(PortfolioError):
        p.buy(A, qty, D(1))
    with pytest.raises(PortfolioError):
        p.sell(A, qty, D(1))


@pytest.mark.parametrize(
    "price",
    [D(0), D("-1"), D("NaN"), D("Infinity"), MAX_AMOUNT, D("1E-21"), D("1E+14"), 10, 10.5, "10", None, True],
)
def test_invalid_prices_are_rejected_for_buy_and_sell(price):
    p = held("1000000", (A, 10))
    with pytest.raises(PortfolioError):
        p.buy(A, D(1), price)
    with pytest.raises(PortfolioError):
        p.sell(A, D(1), price)


def test_instrument_must_be_an_instrument():
    with pytest.raises(PortfolioError):
        Portfolio.initial(D(10)).buy("AAA", D(1), D(1))
    with pytest.raises(PortfolioError):
        held("0", (A, 1)).sell(("AAA", Exchange.NSE), D(1), D(1))


# ---- MAX_AMOUNT boundaries ------------------------------------------------------------------------------------------


def test_exact_context_traps_inexact_when_an_operation_really_needs_rounding():
    ctx = EXACT_CONTEXT
    assert ctx.traps[Inexact] and ctx.prec == 100  # the contract: wide, and never allowed to round
    with pytest.raises(Inexact):
        ctx.divide(D(1), D(3))  # 0.333... has no finite exact form
    big = D("1" * 60)
    with pytest.raises(Inexact):
        ctx.multiply(big, big)  # 119 significant digits do not fit 100
    assert MONEY_CONTEXT.multiply(big, big) != D(int("1" * 60) ** 2)  # the narrow context silently rounds instead
    assert ctx.multiply(D("1" * 30), D("1" * 30)) == D(int("1" * 30) ** 2)  # fits: exact, no error


def test_portfolio_arithmetic_helper_turns_a_trapped_rounding_into_a_portfolio_error():
    big = D("1" * 60)
    with pytest.raises(PortfolioError) as err:
        portfolio._exact("multiply", big, big)  # unreachable through validated inputs, so called directly
    assert isinstance(err.value.__cause__, Inexact)


def test_a_trade_notional_at_or_above_max_amount_is_an_input_error_not_a_rejection():
    p = Portfolio.initial(MAX_AMOUNT - 1)
    with pytest.raises(PortfolioError) as err:
        p.buy(A, D(2), MAX_AMOUNT - 1)  # notional 2 x (10^15 - 1)
    assert not isinstance(err.value, InsufficientCash)
    assert p.buy(A, D(1), MAX_AMOUNT - 1).cash == 0  # exactly below the bound is allowed


def test_a_sell_that_would_push_cash_to_max_amount_is_an_input_error():
    p = held(MAX_AMOUNT - 1, (A, 1))
    with pytest.raises(PortfolioError) as err:
        p.sell(A, D(1), D(2))
    assert not isinstance(err.value, (InsufficientCash, InsufficientPosition))


def test_a_sell_landing_exactly_on_the_last_value_below_max_amount_is_allowed():
    p = held(MAX_AMOUNT - 2, (A, 1))
    assert p.sell(A, D(1), D(1)).cash == MAX_AMOUNT - 1


# ---- marking --------------------------------------------------------------------------------------------------------


def test_mark_values_positions_and_equity_from_explicit_prices():
    p = held("500.25", (A, 10), (B, 3))
    v = p.mark({A: D("1250.5"), B: D("99.99")})
    assert v == Valuation(cash=D("500.25"), positions_value=D("12804.97"), equity=D("13305.22"))
    assert v.positions_value == D("12505.0") + D("299.97")  # 10 x 1250.5 + 3 x 99.99


def test_mark_of_an_empty_portfolio_is_cash_only_and_needs_no_prices():
    v = Portfolio.initial(D("42.5")).mark({})
    assert (v.cash, v.positions_value, v.equity) == (D("42.5"), D(0), D("42.5"))


def test_mark_never_substitutes_a_missing_price():
    with pytest.raises(PortfolioError):
        held("0", (A, 1), (B, 1)).mark({A: D(1)})


def test_mark_rejects_prices_for_instruments_that_are_not_held():
    p = held("0", (A, 2))
    assert p.mark({A: D(3)}).equity == D(6)
    with pytest.raises(PortfolioError, match="not held"):
        p.mark({A: D(3), B: D(99)})
    with pytest.raises(PortfolioError, match="not held"):
        Portfolio.initial(D(5)).mark({A: D(1)})  # nothing held, so any price is extra
    with pytest.raises(PortfolioError):
        p.mark({A: D(3), B: D(0)})  # an invalid extra price is still an error


def test_mark_requires_exactly_one_price_per_held_instrument():
    p = held("0", (A_BSE, 3), (A, 1), (B, 2))
    prices = {A: D(10), B: D(20), A_BSE: D(30)}
    assert p.mark(prices).positions_value == D(10 + 40 + 90)
    for dropped in prices:
        with pytest.raises(PortfolioError, match="no price"):
            p.mark({k: v for k, v in prices.items() if k != dropped})


@pytest.mark.parametrize("key", ["AAA", ("AAA", Exchange.NSE), None])
def test_mark_rejects_keys_that_are_not_instruments(key):
    with pytest.raises(PortfolioError):
        held("0", (A, 1)).mark({A: D(1), key: D(1)})


@pytest.mark.parametrize("price", [D(0), D("-1"), D("NaN"), D("Infinity"), MAX_AMOUNT, 5, 5.5, None])
def test_mark_rejects_invalid_prices(price):
    with pytest.raises(PortfolioError):
        held("0", (A, 1)).mark({A: price})


def test_mark_rejects_a_non_mapping_prices_argument():
    with pytest.raises(PortfolioError):
        held("0", (A, 1)).mark([(A, D(1))])


def test_mark_bounds_a_position_value_and_equity_below_max_amount():
    with pytest.raises(PortfolioError):
        held("0", (A, 10**14)).mark({A: D(100)})  # position value 10^16
    with pytest.raises(PortfolioError):
        held(MAX_AMOUNT - 1, (A, 1)).mark({A: D(5)})  # equity (10^15 - 1) + 5
    with pytest.raises(PortfolioError):  # each position below the bound, their sum not
        held("0", (A, 1), (B, 1)).mark({A: MAX_AMOUNT - 1, B: MAX_AMOUNT - 1})
    assert held("0", (A, 1)).mark({A: MAX_AMOUNT - 1}).equity == MAX_AMOUNT - 1


def test_valuation_is_frozen_and_validated():
    v = Portfolio.initial(D(1)).mark({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.equity = D(2)
    with pytest.raises(PortfolioError):
        Valuation(cash=D(1), positions_value=D(1), equity=D(3))  # equity must equal cash + positions_value


# ---- immutability and determinism -----------------------------------------------------------------------------------


def test_portfolio_is_frozen_hashable_and_stores_only_immutable_containers():
    p = held("10", (A, 2))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.cash = D(0)
    assert isinstance(p.positions, tuple) and all(isinstance(pair, tuple) for pair in p.positions)
    assert hash(p) == hash(held("10", (A, 2)))


def test_the_mapping_view_is_read_only_and_a_copy_cannot_reach_internal_state():
    p = held("10", (A, 2))
    view = p.as_mapping()
    assert isinstance(view, MappingProxyType) and view[A] == D(2)
    with pytest.raises(TypeError):
        view[A] = D(99)
    with pytest.raises(TypeError):
        del view[A]
    with pytest.raises(TypeError):
        view[B] = D(1)
    copy = dict(view)
    copy[A] = D(99)
    copy[B] = D(1)
    assert p.quantity(A) == D(2) and p.quantity(B) == D(0) and p.positions == ((A, D(2)),)
    assert p.as_mapping() is not view and dict(p.as_mapping()) == {A: D(2)}


def test_repeated_equivalent_operations_give_equal_results():
    def run():
        return Portfolio.initial(D("100000")).buy(A, D(10), D("101.5")).buy(B, D(3), D("20")).sell(A, D(4), D("110"))

    one, two = run(), run()
    assert one == two and hash(one) == hash(two) and one.mark({A: D(111), B: D(21)}) == two.mark({B: D(21), A: D(111)})


def test_buy_order_across_instruments_does_not_change_the_final_state():
    base = Portfolio.initial(D("100000"))
    assert base.buy(A, D(1), D(10)).buy(B, D(2), D(20)) == base.buy(B, D(2), D(20)).buy(A, D(1), D(10))
