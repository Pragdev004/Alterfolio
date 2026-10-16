"""Backtest config, strategy identity, errors and Unavailable (Feature 005 step 1)."""

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.domain.enums import Currency
from app.domain.numeric import MAX_AMOUNT
from app.quant.backtest.config import (
    PRICE_BASIS,
    BacktestConfig,
    BacktestInputError,
    StrategyIdentity,
    Unavailable,
)

START, END = date(2026, 1, 1), date(2026, 3, 31)


def cfg(**over):
    kw = dict(start_date=START, end_date=END, initial_cash=D("100000"), currency=Currency.INR, trial_count=1)
    kw.update(over)
    return BacktestConfig(**kw)


def test_valid_config_keeps_values_and_defaults_to_the_documented_basis():
    c = cfg()
    assert (c.start_date, c.end_date, c.initial_cash, c.currency) == (START, END, D("100000"), Currency.INR)
    assert c.price_basis == PRICE_BASIS == "SPLIT_ADJUSTED_OPEN_CLOSE"
    assert cfg(start_date=END, end_date=END).start_date == END  # one-day range is valid


def test_input_error_is_a_value_error():
    assert issubclass(BacktestInputError, ValueError)


@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), "2026-01-01", None])
def test_dates_must_be_plain_dates(bad):
    with pytest.raises(BacktestInputError):
        cfg(start_date=bad)
    with pytest.raises(BacktestInputError):
        cfg(end_date=bad)


def test_start_after_end_rejected():
    with pytest.raises(BacktestInputError):
        cfg(start_date=END, end_date=START)


@pytest.mark.parametrize(
    "bad",
    [D("0"), D("-1"), D("NaN"), D("Infinity"), MAX_AMOUNT, MAX_AMOUNT + 1, D("1E+30"), D("0.1E-25"), 100, 100.0, "100", True],
)
def test_initial_cash_must_be_a_positive_bounded_decimal(bad):
    with pytest.raises(BacktestInputError):
        cfg(initial_cash=bad)


def test_initial_cash_just_below_the_bound_is_valid_and_kept_exactly():
    c = cfg(initial_cash=MAX_AMOUNT - 1)
    assert c.initial_cash == MAX_AMOUNT - 1
    assert cfg(initial_cash=D("100.50")).initial_cash.as_tuple() == D("100.50").as_tuple()  # no normalization


def test_currency_must_be_a_currency():
    with pytest.raises(BacktestInputError):
        cfg(currency="INR")


@pytest.mark.parametrize("bad", ["", "ADJUSTED", "split_adjusted_open_close", None])
def test_unsupported_price_basis_rejected(bad):
    with pytest.raises(BacktestInputError):
        cfg(price_basis=bad)


def test_config_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg().initial_cash = D("1")


# ---- StrategyIdentity -----------------------------------------------------------------------------------------------


def test_identity_from_mapping_is_sorted_canonical_text():
    ident = StrategyIdentity.create(
        "buy-hold", "1", {"zeta": D("1.50"), "alpha": 3, "mid": "fast"}
    )
    assert ident.parameters == (("alpha", "3"), ("mid", "fast"), ("zeta", "1.5"))
    assert (ident.strategy_id, ident.version) == ("buy-hold", "1")


def test_identity_is_independent_of_mapping_order_and_of_later_mutation():
    params = {"b": 2, "a": 1}
    one = StrategyIdentity.create("s", "1", params)
    params["c"] = 9
    two = StrategyIdentity.create("s", "1", {"a": 1, "b": 2})
    assert one == two and one.parameters == (("a", "1"), ("b", "2"))
    assert isinstance(one.parameters, tuple) and all(isinstance(p, tuple) for p in one.parameters)


def test_identity_without_parameters_is_valid():
    assert StrategyIdentity.create("s", "1", {}).parameters == ()


@pytest.mark.parametrize("bad", [1.5, True, None, [1], D("NaN"), D("Infinity")])
def test_identity_rejects_non_canonical_parameter_values(bad):
    with pytest.raises(BacktestInputError):
        StrategyIdentity.create("s", "1", {"p": bad})


@pytest.mark.parametrize("key", ["", " ", 1, "a\x00b"])
def test_identity_rejects_bad_parameter_keys(key):
    with pytest.raises(BacktestInputError):
        StrategyIdentity.create("s", "1", {key: 1})


@pytest.mark.parametrize("bad", ["", "  ", None, 1, "a\x00b", "x" * 65])
def test_identity_id_and_version_must_be_bounded_non_empty_text(bad):
    with pytest.raises(BacktestInputError):
        StrategyIdentity.create(bad, "1", {})
    with pytest.raises(BacktestInputError):
        StrategyIdentity.create("s", bad, {})


def test_direct_construction_must_already_be_canonical():
    StrategyIdentity("s", "1", (("a", "1"), ("b", "2")))
    for params in ((("b", "1"), ("a", "2")), (("a", "1"), ("a", "2")), (("a", 1),), [("a", "1")], (("a",),)):
        with pytest.raises(BacktestInputError):
            StrategyIdentity("s", "1", params)


def test_identity_is_frozen_and_hashable():
    ident = StrategyIdentity.create("s", "1", {"a": 1})
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.version = "2"
    assert hash(ident) == hash(StrategyIdentity.create("s", "1", {"a": 1}))
    assert StrategyIdentity.create("s", "2", {"a": 1}) != ident  # a new version is a different identity


# ---- Unavailable ----------------------------------------------------------------------------------------------------


def test_unavailable_carries_a_non_empty_reason_and_is_frozen():
    u = Unavailable("insufficient history")
    assert u.reason == "insufficient history"
    with pytest.raises(dataclasses.FrozenInstanceError):
        u.reason = "x"
    for bad in ("", "  ", None, 3):
        with pytest.raises(BacktestInputError):
            Unavailable(bad)


def test_aware_datetime_is_not_accepted_as_a_date():
    with pytest.raises(BacktestInputError):
        cfg(start_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
