"""Backtest trial_count (Feature 005, gate D7): required, validated, recorded in the result and fingerprint."""

import dataclasses
from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.enums import Currency
from app.quant.backtest.config import BacktestConfig, BacktestInputError
from app.quant.backtest.engine import run_backtest
from tests.backtest_helpers import A, PRICES, WEEK, Scripted, config, make_series

D1 = WEEK[0]


def run(trial_count=1):
    return run_backtest([make_series(prices=PRICES)], config(trial_count=trial_count), Scripted({D1: {A: D(10)}}, "1"))


def test_trial_count_is_required():
    with pytest.raises(TypeError):
        BacktestConfig(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), initial_cash=D("1"), currency=Currency.INR)


@pytest.mark.parametrize("bad", [0, -1, -100, True, False, 1.0, 2.5, "3", None, D("2")])
def test_trial_count_rejects_zero_negative_bool_and_non_int(bad):
    with pytest.raises(BacktestInputError):
        config(trial_count=bad)


@pytest.mark.parametrize("good", [1, 2, 10_000])
def test_trial_count_accepts_ints_from_one(good):
    assert config(trial_count=good).trial_count == good


def test_trial_count_appears_in_to_dict_inputs():
    assert run(7).to_dict()["inputs"]["config"]["trial_count"] == 7
    assert run(7).config.trial_count == 7


def test_changing_trial_count_changes_only_the_fingerprint_and_the_recorded_value():
    one, two = run(1), run(2)
    assert one.fingerprint != two.fingerprint
    assert run(2).fingerprint == two.fingerprint  # deterministic for the same value
    a, b = one.to_dict(), two.to_dict()
    assert a["inputs"]["config"]["trial_count"] == 1 and b["inputs"]["config"]["trial_count"] == 2
    a["inputs"]["config"]["trial_count"] = b["inputs"]["config"]["trial_count"] = None
    a["provenance"]["result_fingerprint"] = b["provenance"]["result_fingerprint"] = None
    assert a == b  # everything else is identical


def test_config_stays_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        config().trial_count = 2
