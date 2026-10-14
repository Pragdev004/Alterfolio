"""Feature 008 audit: defaults through the public entry point, 9 vs 10 trips, downstream independence, serialization."""

import json
from decimal import Context, Decimal as D

import pytest

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.cost_basis import fold_positions
from app.quant.bias_cost.types import BiasAnalysisResult
from app.quant.bias_cost.validation import validate_inputs
from app.quant.luck_test.types import LuckResult
from app.quant.regime_split import classify
from app.quant.regime_split.analysis import analyze_regimes
from app.quant.regime_split.errors import RegimeInputError, UnavailableReason
from app.quant.regime_split.trips import map_round_trips
from app.quant.regime_split.types import Regime, RegimeParameters
from luck_helpers import series as luck_series
from regime_helpers import (
    BUY, OWN, SELL, bias_params, led, ledger, long_series, luck_params, small, world,
)

OTHER = Instrument("OTHERTEST", Exchange.NSE)


def public(trades, mapping, parameters=None, *, reviewed=frozenset(), universe=(), members=()):
    return analyze_regimes(trades, mapping, universe, members, frozenset(), bias_params(), luck_params(),
                           parameters or RegimeParameters(), corporate_action_reviewed=reviewed)


def trip_at(day: int, tag: str):
    return [led(f"B{tag}", BUY, 10, 100, day, hour=4), led(f"S{tag}", SELL, 10, 101, day, hour=5)]


# ---- Audit 1: production defaults, exercised through the real entry point -----------------------------------------------

def test_defaults_are_60_sessions_33_67_120_observations_and_10_trips():
    p = RegimeParameters()
    assert (p.volatility_window, p.low_percentile, p.high_percentile, p.min_calibration, p.min_trips_per_regime) == (
        60, 33, 67, 120, 10)


def test_default_history_and_calibration_boundaries_through_analyze_regimes():
    trades = [t for day in (60, 61, 179, 180, 181, 182) for t in trip_at(day, f"{day:03d}")]
    result = public(trades, {OWN: long_series(OWN)})
    rows = {t.trip_id: t for t in result.trips}
    assert rows["B060"].unavailable.reason is UnavailableReason.INSUFFICIENT_HISTORY  # 60 closes before: not enough
    assert rows["B060"].volatility is None
    # 61 closes: v is computable but the pool is empty
    assert rows["B061"].unavailable.reason is UnavailableReason.INSUFFICIENT_CALIBRATION
    assert rows["B061"].volatility is not None and rows["B061"].calibration_count is None
    assert rows["B061"].unavailable.detail == "0 prior observations, need 120"
    assert rows["B179"].unavailable.detail == "118 prior observations, need 120"
    assert rows["B180"].unavailable.reason is UnavailableReason.INSUFFICIENT_CALIBRATION  # 119 prior observations
    assert rows["B180"].unavailable.detail == "119 prior observations, need 120"
    assert rows["B180"].low_threshold is None and rows["B180"].high_threshold is None
    for tid in ("B181", "B182"):  # 181 bars before: exactly 120 (then 121) prior observations
        assert rows[tid].unavailable is None and rows[tid].regime in (Regime.LOW, Regime.NORMAL, Regime.HIGH)
    assert rows["B181"].calibration_count == 120 and rows["B182"].calibration_count == 121
    assert rows["B181"].low_threshold < rows["B181"].high_threshold


def test_label_uses_only_the_listing_s_own_history_through_analyze_regimes():
    other_trades = [led(f"Y{d}", t, 10, 100, d, instrument=OTHER) for d, t in ((190, BUY), (191, SELL))]
    trades = trip_at(190, "190") + other_trades
    base = public(trades, {OWN: long_series(OWN), OTHER: long_series(OTHER, k=3)})
    changed = public(trades, {OWN: long_series(OWN), OTHER: long_series(OTHER, k=9)})
    own = lambda r: next(t for t in r.trips if t.trip_id == "B190")  # noqa: E731
    assert own(base) == own(changed) and own(base).regime is not None
    assert next(t for t in base.trips if t.trip_id == "Y190") != next(t for t in changed.trips if t.trip_id == "Y190")


def test_invalid_volatility_raises(monkeypatch):
    """MarketBar already refuses a non-positive close (test_regime_split_classify covers the classifier's own guard)."""
    trades = trip_at(190, "190")
    series = long_series(OWN)
    for bad in (None, float("inf"), float("nan")):
        monkeypatch.setattr(classify, "volatility", lambda view, lookback, v=bad: v)
        with pytest.raises(RegimeInputError, match="finite"):
            public(trades, {OWN: series})
    with pytest.raises(ValueError):
        type(series.bars[0])(**{**series.bars[0].__dict__, "close": D(0)})


# ---- Audit 2: unavailable propagation ---------------------------------------------------------------------------------

def _declared(universe):
    return frozenset({OWN} | {c.instrument for c in universe})


def _subset(trades, ids):
    keep = {i[1:] for i in ids}
    return [t for t in trades if t.trade_id[1:] in keep]


def test_nine_versus_ten_classified_trips():
    mapping, universe, members = world()
    trades = ledger(range(10, 108, 3))
    declared = _declared(universe)
    everything = analyze_regimes(trades, mapping, universe, members, frozenset(), bias_params(), luck_params(),
                                 small(min_trips_per_regime=1), corporate_action_reviewed=declared)
    ids_by_regime = {b.regime: b.trip_ids for b in everything.blocks}
    regime, ids = max(ids_by_regime.items(), key=lambda kv: len(kv[1]))
    assert len(ids) >= 10, "the fixture must put at least ten trips in one regime"
    for count, runs in ((9, False), (10, True)):
        chosen = ids[:count]
        kept = _subset(trades, chosen)
        result = analyze_regimes(kept, mapping, universe, members, frozenset(), bias_params(), luck_params(),
                                 small(min_trips_per_regime=10), corporate_action_reviewed=declared)
        block = next(b for b in result.blocks if b.regime is regime)
        assert len(block.trip_ids) == count
        if runs:
            assert isinstance(block.luck, LuckResult) and isinstance(block.bias, BiasAnalysisResult)
            assert len(block.luck.trips) == 10
        else:
            for part in (block.luck, block.bias):
                assert part.reason is UnavailableReason.INSUFFICIENT_TRIPS_IN_REGIME
                assert part.detail == "9 classified trips, need 10"
            assert block.trip_ids == tuple(chosen)  # ids and the labels stay available below the minimum
            assert {t.trip_id for t in result.trips if t.regime is regime} == set(chosen)
            assert all(t.low_threshold is not None and t.calibration_count is not None
                       for t in result.trips if t.regime is not None)


def test_one_downstream_analysis_unavailable_leaves_the_other_intact():
    mapping, universe, members = world()
    trades = ledger(range(10, 108, 3))
    args = (trades, mapping, universe, members, frozenset(), bias_params(), luck_params())
    undeclared = analyze_regimes(*args, small(min_trips_per_regime=1), corporate_action_reviewed=None)
    block = max(undeclared.blocks, key=lambda b: len(b.trip_ids))
    assert block.luck.unavailable.reason.value == "CORPORATE_ACTION_COVERAGE_UNDECLARED"
    ids = set(block.trip_ids)
    direct = analyze_biases([t for t in trades if t.trade_id[1:] in {i[1:] for i in ids}], mapping, bias_params(), frozenset())
    assert block.bias == direct and any(r.metric.cost_inr is not None or r.metric.unavailable for r in block.bias.results)
    # the other way round: 006's own gate (fewer than ten round trips) leaves 007 intact
    declared = analyze_regimes(*args, small(min_trips_per_regime=1), corporate_action_reviewed=_declared(universe))
    small_block = next(b for b in declared.blocks if 0 < len(b.trip_ids) < 10)
    assert isinstance(small_block.luck, LuckResult) and small_block.luck.unavailable is None
    assert "insufficient history" in small_block.bias.profile.reason
    assert {r.metric.bias.value for r in small_block.bias.results} == {"DISPOSITION", "CHASING", "OVERTRADING"}


def test_serialization_keeps_unavailable_reasons_and_regime_metadata():
    mapping, universe, members = world()
    trades = ledger(range(10, 108, 3))
    result = analyze_regimes(trades, mapping, universe, members, frozenset(), bias_params(), luck_params(),
                             small(min_trips_per_regime=1), corporate_action_reviewed=None)
    data = json.loads(json.dumps(result.to_dict()))
    rows = {r["trip_id"]: r for r in data["values"]["trips"]}
    early = next(r for r in rows.values() if r["regime"] is None)
    assert early["unavailable"]["reason"] in ("INSUFFICIENT_HISTORY", "INSUFFICIENT_CALIBRATION") and early["unavailable"]["detail"]
    labelled = next(r for r in rows.values() if r["regime"] is not None)
    assert labelled["low_threshold"] < labelled["high_threshold"] and labelled["calibration_count"] >= 10
    assert labelled["unavailable"] is None and labelled["volatility"] is not None
    big = max(data["values"]["regimes"], key=lambda r: r["trip_count"])
    assert big["luck"]["unavailable"]["reason"] == "CORPORATE_ACTION_COVERAGE_UNDECLARED"
    assert big["bias"]["input_fingerprint"] and [m["bias"] for m in big["bias"]["metrics"]] == [
        "DISPOSITION", "CHASING", "OVERTRADING"]
    gated = analyze_regimes(trades, mapping, universe, members, frozenset(), bias_params(), luck_params(),
                            small(min_trips_per_regime=1000)).to_dict()
    empty = gated["values"]["regimes"][0]
    assert len(empty["trip_ids"]) == empty["trip_count"] and empty["luck"]["unavailable"]["reason"] == "INSUFFICIENT_TRIPS_IN_REGIME" and empty["bias"]["unavailable"]["reason"] == "INSUFFICIENT_TRIPS_IN_REGIME"
    missing = analyze_regimes(trades, {}, universe, members, frozenset(), bias_params(), luck_params(), small())
    assert missing.to_dict()["unavailable"]["reason"] == "NO_TRIP_SERIES"


# ---- Audit 3: Decimal and identity ---------------------------------------------------------------------------------------

def test_cost_and_proceeds_use_exact_arithmetic_beyond_the_default_decimal_context():
    qty, buy, sell = D("12345.6789012345"), D("98765.4321098765"), D("98766.4321098765")
    trades = [led("A1", BUY, qty, buy, 20), led("A2", SELL, qty, sell, 21)]
    inputs = validate_inputs(trades, {OWN: luck_series(OWN, 0)}, bias_params())
    trip = map_round_trips(fold_positions(inputs).round_trips)[0].trip
    exact = Context(prec=200)
    assert trip.cost_inr == exact.multiply(qty, buy) and trip.proceeds_inr == exact.multiply(qty, sell)
    assert len(trip.cost_inr.as_tuple().digits) > 28  # a 28-digit default context would have rounded this


def test_trip_values_are_identical_alone_or_with_the_full_ledger():
    one, two = trip_at(20, "X"), trip_at(30, "Y")

    def trips_of(trades):
        inputs = validate_inputs(trades, {OWN: luck_series(OWN, 0)}, bias_params())
        return {m.trip.trip_id: m.trip for m in map_round_trips(fold_positions(inputs).round_trips)}

    together = trips_of(one + two)
    assert trips_of(two)["BY"] == together["BY"] and trips_of(one)["BX"] == together["BX"]


# ---- Audit 4: ordering ------------------------------------------------------------------------------------------------

def test_output_order_is_by_open_close_then_trip_id():
    trades = [led("Z1", BUY, 1, 100, 190, hour=4), led("Z2", SELL, 1, 100, 190, hour=5),
              led("A1", BUY, 1, 100, 190, hour=6), led("A2", SELL, 1, 100, 190, hour=7),
              led("M1", BUY, 1, 100, 185), led("M2", SELL, 1, 100, 188)]
    result = public(trades, {OWN: long_series(OWN)})
    keys = [(t.open_session, t.close_session, t.trip_id) for t in result.trips]
    assert keys == sorted(keys) and [t.trip_id for t in result.trips] == ["M1", "A1", "Z1"]
    assert result == public(list(reversed(trades)), {OWN: long_series(OWN)})
    for b in result.blocks:
        order = {t.trip_id: i for i, t in enumerate(result.trips)}
        assert [order[i] for i in b.trip_ids] == sorted(order[i] for i in b.trip_ids)
