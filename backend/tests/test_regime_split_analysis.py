"""Feature 008 orchestration: partition, the minimum-trips gate, Feature 006/007 propagation, determinism, serialization."""

import json
import random
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.types import BiasAnalysisResult
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.types import LuckResult
from app.quant.regime_split.analysis import analyze_regimes
from app.quant.regime_split.errors import RegimeInputError, UnavailableReason
from app.quant.regime_split.types import Regime
from regime_helpers import BUY, OWN, SELL, bias_params, led, ledger, luck_params, reviewed_all, small, world


def run(trades=None, *, regime=None, mapping=None, luck_kw=None, trades_kw=None, reviewed="all"):
    series, universe, members = world()
    if mapping is not None:
        series = mapping(series)
    trades = list(ledger(**(trades_kw or {})) if trades is None else trades)
    trips = {OWN}
    declared = reviewed_all([type("T", (), {"instrument": i}) for i in trips], universe) if reviewed == "all" else reviewed
    return analyze_regimes(trades, series, universe, members, frozenset(), bias_params(), luck_params(**(luck_kw or {})),
                           regime or small(), corporate_action_reviewed=declared), series, universe, members, trades


def test_every_round_trip_is_in_exactly_one_place():
    result, *_ = run(regime=small(min_trips_per_regime=1))
    assert result.round_trip_count == len(result.trips) == 33
    labelled = [t for t in result.trips if t.regime is not None]
    assert sum(len(b.trip_ids) for b in result.blocks) == len(labelled)
    assert [b.regime for b in result.blocks] == [Regime.LOW, Regime.NORMAL, Regime.HIGH]
    for b in result.blocks:
        assert set(b.trip_ids) == {t.trip_id for t in labelled if t.regime is b.regime}
    early = [t for t in result.trips if t.regime is None]
    assert early and all(t.unavailable.reason in (UnavailableReason.INSUFFICIENT_HISTORY,
                                                  UnavailableReason.INSUFFICIENT_CALIBRATION) for t in early)
    assert [t.open_session for t in result.trips] == sorted(t.open_session for t in result.trips)


def test_the_minimum_gates_only_the_regime_level_aggregates():
    result, *_ = run(regime=small(min_trips_per_regime=1000))
    labelled = [t for t in result.trips if t.regime is not None]
    assert labelled and result.round_trip_count == 33  # labels, counts and ids do not depend on the minimum
    for b in result.blocks:
        assert b.luck.reason is UnavailableReason.INSUFFICIENT_TRIPS_IN_REGIME and b.bias.reason is b.luck.reason
        assert b.luck.detail == f"{len(b.trip_ids)} classified trips, need 1000"
    same, *_ = run(regime=small(min_trips_per_regime=1))
    assert [t for t in same.trips] == list(result.trips)


def test_at_or_above_the_minimum_runs_the_unchanged_feature_007_and_006_on_that_regimes_trips():
    result, series, universe, members, trades = run(regime=small(min_trips_per_regime=1))
    big = max(result.blocks, key=lambda b: len(b.trip_ids))
    assert isinstance(big.luck, LuckResult) and isinstance(big.bias, BiasAnalysisResult)
    assert {t.trip_id for t in big.luck.trips} == set(big.trip_ids)
    mine = {t.trade_id for t in trades if t.trade_id[1:] in {i[1:] for i in big.trip_ids}}
    expected_bias = analyze_biases([t for t in trades if t.trade_id in mine], series, bias_params(), frozenset())
    assert big.bias == expected_bias
    mapped_trip = next(t for t in big.luck.trips if t.trip_id == big.trip_ids[0])
    assert mapped_trip.trip_id == big.trip_ids[0]
    empty = [b for b in result.blocks if not b.trip_ids]
    for b in empty:  # an empty regime is Unavailable, never a zero result
        assert b.luck.reason is UnavailableReason.INSUFFICIENT_TRIPS_IN_REGIME


def test_feature_007_unavailable_reasons_are_propagated_untouched():
    result, *_ = run(regime=small(min_trips_per_regime=1), reviewed=None)  # undeclared corporate-action coverage
    big = max(result.blocks, key=lambda b: len(b.trip_ids))
    assert big.luck.unavailable.reason.value == "CORPORATE_ACTION_COVERAGE_UNDECLARED"
    assert all(not t.evaluated for t in big.luck.trips)


def test_feature_006_below_its_own_minimum_keeps_its_own_reason():
    result, *_ = run(regime=small(min_trips_per_regime=1))
    big = max(result.blocks, key=lambda b: len(b.trip_ids))
    assert len(big.trip_ids) < 10 or big.bias.profile is not None
    if len(big.trip_ids) < 10:
        assert "insufficient history" in big.bias.profile.reason


def test_result_is_deterministic_and_independent_of_input_order():
    first, *_ = run(regime=small(min_trips_per_regime=1))
    again, *_ = run(regime=small(min_trips_per_regime=1))
    assert first == again and first.to_dict() == again.to_dict()
    shuffled = ledger()
    random.Random(3).shuffle(shuffled)
    reordered, *_ = run(shuffled, regime=small(min_trips_per_regime=1))
    assert reordered == first and reordered.input_fingerprint == first.input_fingerprint


def test_fingerprint_changes_with_inputs_and_parameters():
    base, *_ = run(regime=small(min_trips_per_regime=1))
    assert run(regime=small(min_trips_per_regime=2))[0].input_fingerprint != base.input_fingerprint
    assert run(luck_kw={"seed": 8}, regime=small(min_trips_per_regime=1))[0].input_fingerprint != base.input_fingerprint
    changed = ledger()
    changed[0] = led("B010", BUY, 10, 150, 10)
    assert run(changed, regime=small(min_trips_per_regime=1))[0].input_fingerprint != base.input_fingerprint


def test_the_label_ignores_everything_on_or_after_the_opening_date():
    base, *_ = run()
    d = next(t for t in base.trips if t.regime is not None)

    def bump(series):
        s = series[OWN]
        from datetime import datetime, timezone
        bars = tuple(replace(b, open=b.open * 2, high=b.high * 2, low=b.low * 2, close=b.close * 2, adjusted_close=b.adjusted_close * 2)
                     if b.session_date >= d.open_session else b for b in s.bars)
        return {**series, OWN: replace(s, bars=bars)}

    moved, *_ = run(mapping=bump)
    same = next(t for t in moved.trips if t.trip_id == d.trip_id)
    assert (same.regime, same.volatility, same.low_threshold, same.high_threshold) == (
        d.regime, d.volatility, d.low_threshold, d.high_threshold)


def test_empty_ledger_gives_three_unavailable_blocks():
    result, *_ = run([])
    assert result.round_trip_count == 0 and result.trips == () and result.unavailable is None
    assert all(b.trip_ids == () and b.luck.reason is UnavailableReason.INSUFFICIENT_TRIPS_IN_REGIME for b in result.blocks)


def test_a_listing_without_a_series_makes_the_whole_result_unavailable():
    result, *_ = run(mapping=lambda s: {k: v for k, v in s.items() if k != OWN})
    assert result.unavailable.reason is UnavailableReason.NO_TRIP_SERIES and result.round_trip_count == 0


def test_an_isin_buy_and_a_null_isin_sell_never_form_a_trip():
    # Changed by owner instruction (ISIN-keyed positions): a legacy NULL-ISIN row is a separate position from an ISIN row, so the
    # mixed pair can no longer become one trip with AMBIGUOUS_ISIN (that guard now only protects hand-built trips).
    trades = ledger(range(10, 40, 3))
    trades[0] = led("B010", BUY, 10, 100 + 10 % 7, 10, isin="INE000000001")
    result, *_ = run(trades, regime=small(min_trips_per_regime=1))
    assert "B010" not in {t.trip_id for t in result.trips}


def test_invalid_inputs_raise():
    series, universe, members = world()
    args = ([], series, universe, members, frozenset(), bias_params(), luck_params())
    with pytest.raises(RegimeInputError):
        analyze_regimes(*args, "not parameters")
    with pytest.raises(RegimeInputError):
        analyze_regimes(*args[:6], "not luck parameters", small())
    with pytest.raises(ValueError):
        analyze_regimes([led("X1", SELL, 1, 1, 20), led("X2", SELL, 1, 1, 21), led("X3", BUY, 1, 1, 22),
                         led("X4", SELL, 5, 1, 23)], *args[1:], small())  # oversell: Feature 006's own input error


def test_serialization_follows_the_spec_shape():
    result, *_ = run(regime=small(min_trips_per_regime=1))
    data = json.loads(json.dumps(result.to_dict()))
    assert list(data) == ["schema_version", "as_of", "unavailable", "provenance", "inputs", "values"]
    assert data["schema_version"] == 1 and data["unavailable"] is None
    assert data["provenance"]["formula_version"] == "regime-v1" and data["provenance"]["limitations"]
    assert data["inputs"]["parameters"]["volatility_window"] == 5
    assert [r["regime"] for r in data["values"]["regimes"]] == ["LOW", "NORMAL", "HIGH"]
    assert data["values"]["unclassified_count"] == sum(1 for t in data["values"]["trips"] if t["regime"] is None)
    gated, *_ = run(regime=small(min_trips_per_regime=1000))
    assert json.loads(json.dumps(gated.to_dict()))["values"]["regimes"][0]["luck"]["unavailable"]["reason"] == (
        "INSUFFICIENT_TRIPS_IN_REGIME")


def test_money_stays_decimal():
    result, *_ = run(regime=small(min_trips_per_regime=1))
    big = max(result.blocks, key=lambda b: len(b.trip_ids))
    assert all(r.metric.cost_inr is None or isinstance(r.metric.cost_inr, D) for r in big.bias.results)
