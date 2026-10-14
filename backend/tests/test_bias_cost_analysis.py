"""Feature 006: archetype rules, orchestration, listings, fingerprints, determinism (spec sections 3, 4, 5, 6)."""
import dataclasses
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest
from bias_helpers import BSE_A, BUY, NSE_A, SELL, WINDOW_START, known, params, series, trade

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.calculations import ChasingFacts, DispositionFacts, OvertradingFacts
from app.quant.bias_cost.errors import BiasInputError, Unavailable
from app.quant.bias_cost.profile import classify_behaviour
from app.quant.bias_cost.types import BiasKind, FeeStatus


def _result(analysis, kind):
    return next(r for r in analysis.results if r.metric.bias is kind)


def _fp(analysis):
    return {r.metric.bias: r.input_fingerprint for r in analysis.results}


# --- archetype rules (spec 4): thresholds, precedence, denominators, unavailable metrics ------------------------------------
def _classify(closed=10, short=0, eligible=10, chases=0, diff=D("0"), **kw):
    return classify_behaviour(OvertradingFacts(closed, short), ChasingFacts(eligible, chases), DispositionFacts(diff),
                              params(**kw), "fp")


@pytest.mark.parametrize("short,expected", [(3, "CHURNER"), (2, "DISCIPLINED")])
def test_churner_threshold_is_thirty_percent_of_closed_round_trips(short, expected):  # spec 4
    assert _classify(short=short).archetype_id == expected


@pytest.mark.parametrize("chases,expected", [(4, "CHASER"), (3, "DISCIPLINED")])
def test_chaser_threshold_is_forty_percent_of_eligible_buys(chases, expected):  # spec 4
    assert _classify(chases=chases).archetype_id == expected


@pytest.mark.parametrize("diff,expected", [(D("0.10"), "DISPOSITION_PRONE"), (D("0.09"), "DISCIPLINED")])
def test_disposition_threshold_is_pgr_minus_plr_at_least_ten_hundredths(diff, expected):  # spec 4
    assert _classify(diff=diff).archetype_id == expected


def test_first_matching_rule_wins():  # spec 4
    assert _classify(short=10, chases=10, diff=D("1")).archetype_id == "CHURNER"
    assert _classify(chases=10, diff=D("1")).archetype_id == "CHASER"


def test_fewer_than_ten_closed_round_trips_is_unavailable_insufficient_history():  # spec 3
    assert _classify(closed=9, short=9) == Unavailable("insufficient history")
    assert _classify(closed=10).archetype_id == "DISCIPLINED"


def test_unavailable_metrics_are_never_treated_as_zero():  # spec 4
    assert isinstance(_classify(eligible=0), Unavailable)  # chase rule cannot be evaluated, nothing earlier matched
    assert isinstance(_classify(diff=None), Unavailable)
    assert _classify(short=5, eligible=0, diff=None).archetype_id == "CHURNER"  # decided before the missing metric
    assert _classify(chases=5, diff=None).archetype_id == "CHASER"


def test_profile_records_rule_set_version_and_the_metrics_it_used():  # spec 4
    profile = _classify(rule_set_version="archetype-v9")
    assert profile.rule_set_version == "archetype-v9"
    assert dict(profile.supporting_metrics)["closed_round_trips"] == "10"
    assert _classify(diff=D("0.25")) == _classify(diff=D("0.25"))  # repeatable


# --- end to end ---------------------------------------------------------------------------------------------------------
def _listing(k):
    return Instrument(f"S{k:02d}TEST", Exchange.NSE)


def _book(hold=8, winners=6, losers=6, open_loser=False, chase=False):
    """`winners + losers` single-trip listings (buy at 22, sell at 22+hold), plus an optional open listing that is down."""
    trades, serieses = [], []
    for k in range(winners + losers):
        inst, sell_price = _listing(k), 110 if k < winners else 90
        closes = {21: D("110")} if chase else {}
        trades += [trade(f"B{k:02d}", inst, BUY, 10, 100, 22, known()), trade(f"S{k:02d}", inst, SELL, 10, sell_price, 22 + hold, known())]
        serieses.append(series(inst, closes))
    if open_loser:
        inst = _listing(99)
        trades.append(trade("B99", inst, BUY, 10, 100, 22, known()))
        serieses.append(series(inst, {30: D("90")}))
    return trades, {s.instrument: s for s in serieses}


def test_disciplined_book_end_to_end_has_fee_state_and_listing_provenance():  # spec 3, 4, 6
    trades, by_listing = _book()
    analysis = analyze_biases(trades, by_listing, params())
    assert analysis.profile.archetype_id == "DISCIPLINED"
    over = _result(analysis, BiasKind.OVERTRADING).metric
    assert over.cost_inr == D("0") and over.fee_status is FeeStatus.COMPLETE
    assert {p.instrument for p in over.listings} == set(by_listing)
    assert all(p.series_fingerprint == by_listing[p.instrument].fingerprint for p in over.listings)


def test_churner_book_is_classified_by_short_round_trips():  # spec 4
    trades, by_listing = _book(hold=2)
    assert analyze_biases(trades, by_listing, params()).profile.archetype_id == "CHURNER"


def test_chaser_book_is_a_chaser_even_though_its_chasing_cost_is_unavailable():  # spec 4
    trades, by_listing = _book(chase=True)  # buys at 22 follow a +10% run-up in every listing; no non-chase baseline
    analysis = analyze_biases(trades, by_listing, params(chasing_lookback_sessions=20))
    assert _result(analysis, BiasKind.CHASING).metric.cost_inr is None
    assert analysis.profile.archetype_id == "CHASER"


def test_disposition_prone_book_has_a_signed_positive_pgr_minus_plr():  # spec 4
    trades, by_listing = _book(winners=11, losers=1, open_loser=True)
    analysis = analyze_biases(trades, by_listing, params())
    details = dict(_result(analysis, BiasKind.DISPOSITION).metric.details)
    assert D(details["pgr_minus_plr"]) > D("0.10") and analysis.profile.archetype_id == "DISPOSITION_PRONE"


def test_nine_round_trips_give_no_archetype():  # spec 3
    trades, by_listing = _book(winners=5, losers=4)
    assert analyze_biases(trades, by_listing, params()).profile == Unavailable("insufficient history")


# --- listing isolation and exclusions (spec 3, 5) -------------------------------------------------------------------------
def test_missing_series_makes_every_metric_unavailable_and_never_borrows_another_exchange():  # spec 3
    trades = [trade("T1", NSE_A, BUY, 5, 100, 0), trade("T2", NSE_A, SELL, 5, 110, 3)]
    analysis = analyze_biases(trades, {BSE_A: series(BSE_A, {})}, params())  # only the OTHER listing has data
    assert all(r.metric.cost_inr is None and "missing series" in r.metric.unavailable.reason for r in analysis.results)
    assert isinstance(analysis.profile, Unavailable)
    assert all(not r.metric.listings for r in analysis.results)  # BSE data was not used


def test_known_corporate_action_listing_is_excluded_with_a_reason():  # spec 5
    trades, by_listing = _book(winners=1, losers=0)
    analysis = analyze_biases(trades, by_listing, params(), frozenset({_listing(0)}))
    assert any("corporate action" in e.reason for e in analysis.exclusions)
    assert all(r.metric.cost_inr is None for r in analysis.results)  # nothing eligible remains


def test_trade_after_the_series_has_no_bar_excludes_its_listing_not_invents_data():  # spec 5
    trades = [trade("T1", NSE_A, BUY, 5, 100, 5), trade("T2", NSE_A, SELL, 5, 110, 62)]  # series ends at session 59
    analysis = analyze_biases(trades, {NSE_A: series(NSE_A, {})}, params())
    assert any("has no bar" in e.reason for e in analysis.exclusions)
    assert all("no eligible trades" in r.metric.unavailable.reason for r in analysis.results)


def test_pre_window_sell_is_reported_in_analysis_exclusions():  # spec 5
    analysis = analyze_biases([trade("T1", NSE_A, SELL, 5, 100, 3)], {NSE_A: series(NSE_A, {})}, params())
    assert [e.subject for e in analysis.exclusions] == ["T1"]


def test_input_defects_raise_bias_input_error():  # spec 5
    ok, by_listing = [trade("T1", NSE_A, BUY, 5, 100, 0)], {NSE_A: series(NSE_A, {})}
    with pytest.raises(BiasInputError, match="duplicate"):
        analyze_biases(ok + ok, by_listing, params())
    with pytest.raises(BiasInputError, match="window"):
        analyze_biases(ok, by_listing, params(window_start=datetime(2026, 2, 1, tzinfo=timezone.utc)))
    with pytest.raises(BiasInputError, match="not approved"):
        analyze_biases(ok, by_listing, params(formula_version="bias-v2"))
    with pytest.raises(BiasInputError, match="keyed by its own listing"):
        analyze_biases(ok, {BSE_A: series(NSE_A, {})}, params())


# --- fingerprints, determinism, immutability (spec 5, 6) ------------------------------------------------------------------
def test_identical_inputs_give_identical_results_and_fingerprints():  # spec 5
    trades, by_listing = _book()
    first, second = analyze_biases(trades, by_listing, params()), analyze_biases(trades, by_listing, params())
    assert first == second and first.input_fingerprint == second.input_fingerprint


def test_input_permutation_does_not_change_results():  # spec 5
    trades, by_listing = _book()
    forward = analyze_biases(trades, by_listing, params())
    assert analyze_biases(list(reversed(trades)), dict(reversed(list(by_listing.items()))), params()) == forward


def test_each_metric_has_its_own_fingerprint():  # spec 6
    trades, by_listing = _book()
    assert len(set(_fp(analyze_biases(trades, by_listing, params())).values())) == 3


def test_a_charge_change_moves_only_the_overtrading_fingerprint():  # spec 6
    trades, by_listing = _book()
    base = _fp(analyze_biases(trades, by_listing, params()))
    bumped = [dataclasses.replace(t, charges=known("7", "7")) if t.trade_id == "B00" else t for t in trades]
    after = _fp(analyze_biases(bumped, by_listing, params()))
    assert after[BiasKind.OVERTRADING] != base[BiasKind.OVERTRADING]
    assert after[BiasKind.DISPOSITION] == base[BiasKind.DISPOSITION] and after[BiasKind.CHASING] == base[BiasKind.CHASING]


def test_a_sell_price_change_leaves_the_chasing_fingerprint_alone():  # spec 6
    trades, by_listing = _book()
    base = _fp(analyze_biases(trades, by_listing, params()))
    changed = [dataclasses.replace(t, price=D("111")) if t.trade_id == "S00" else t for t in trades]
    after = _fp(analyze_biases(changed, by_listing, params()))
    assert after[BiasKind.CHASING] == base[BiasKind.CHASING]
    assert after[BiasKind.DISPOSITION] != base[BiasKind.DISPOSITION] and after[BiasKind.OVERTRADING] != base[BiasKind.OVERTRADING]


def test_changing_n_or_the_series_changes_the_relevant_fingerprints():  # spec 6
    trades, by_listing = _book()
    base = _fp(analyze_biases(trades, by_listing, params()))
    n_changed = _fp(analyze_biases(trades, by_listing, params(chasing_lookback_sessions=19)))
    assert n_changed[BiasKind.CHASING] != base[BiasKind.CHASING] and n_changed[BiasKind.OVERTRADING] == base[BiasKind.OVERTRADING]
    other = dict(by_listing)
    other[_listing(0)] = series(_listing(0), {55: D("123")})
    series_changed = _fp(analyze_biases(trades, other, params()))
    assert all(series_changed[k] != base[k] for k in base)


def test_results_are_immutable_value_objects():  # spec 6
    trades, by_listing = _book()
    analysis = analyze_biases(trades, by_listing, params())
    assert isinstance(analysis.results, tuple) and isinstance(analysis.exclusions, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        analysis.profile = None
    with pytest.raises(dataclasses.FrozenInstanceError):
        analysis.results[0].metric.cost_inr = D("1")


def test_money_values_are_exact_decimals_not_floats():  # spec 2
    trades, by_listing = _book(winners=11, losers=1, open_loser=True)
    for r in analyze_biases(trades, by_listing, params()).results:
        for value in (r.metric.cost_inr, r.metric.gross_cost_inr, r.metric.fees_known):
            assert value is None or isinstance(value, D)
    assert WINDOW_START.tzinfo is not None and SELL is not BUY
