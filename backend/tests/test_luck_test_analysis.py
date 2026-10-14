"""Feature 007 statistics, bootstrap, seeds, isolation, Unavailable matrix, fingerprints (spec sections 6-9, 10 rows 3-8)."""
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.bootstrap import bootstrap_mean_interval, excess_and_percentile, position
from app.quant.luck_test.errors import LuckInputError, UnavailableReason as R
from app.quant.luck_test.numeric_boundary import CALC, to_float
from app.quant.luck_test.portfolios import compare, nifty_portfolio_returns
from app.quant.luck_test.rng import SplitMix64
from app.quant.luck_test.types import Baseline, IntervalPosition, Membership, TripInput
from luck_helpers import OWN, RETRIEVED, candidate, isin, params, reviewed_all, series, session, trip, world


def many(n, **kw):
    return [trip(f"T{i:02d}", **kw) for i in range(n)]


def run(trips, mapping, universe, members, ca=frozenset(), reviewed="all", **kw):
    """Coverage is a prerequisite: by default the caller declares every traded and universe listing as reviewed."""
    reviewed = reviewed_all(trips, universe) if reviewed == "all" else reviewed
    return analyze_luck(trips, mapping, universe, members, ca, params(**kw), corporate_action_reviewed=reviewed)


def test_per_trip_statistics_are_internally_consistent():  # spec 7
    mapping, universe, members = world(14)
    t = run([trip()], mapping, universe, members).trips[0]
    assert t.actual_return == D("0.1")
    for o in (t.alt, t.nifty):
        assert o.unavailable is None and o.portfolio_count == 50
        assert 0 <= o.beaten and o.beaten + o.ties <= 50
        assert o.percentile == to_float(D(2 * o.beaten + o.ties) / D(100))
        assert o.excess == to_float(t.actual_return - o.mean_return)
    assert t.alt.pool_size == 10 and t.nifty.pool_size == 12


def test_excess_percentile_and_compare_known_values():
    assert excess_and_percentile(D("0.2"), D("0.1"), 3, 2, 10) == (to_float(D("0.1")), 0.4)
    assert compare(D("0.2"), [D("0.1"), D("0.2"), D("0.3"), D("0.2")]) == (1, 2, D("0.2"))


def test_a_valid_zero_is_a_number_not_unavailable():  # spec 8, 10.8
    # every alternative and every Nifty member goes 100 -> 110 over the trip, so every random portfolio returns exactly 0.1
    per = {k: {"override": {70: 100, 80: 110}} for k in range(1, 15)}
    mapping, universe, members = world(14, per=per)
    t = run([trip()], mapping, universe, members).trips[0]
    for o in (t.alt, t.nifty):
        assert o.unavailable is None and o.excess == 0.0 and o.percentile == 0.5
        assert o.ties == 50 and o.beaten == 0 and o.mean_return == D("0.1")


def test_actual_return_uses_ledger_prices_and_alternatives_use_closes():  # spec 3
    mapping, universe, members = world(14)
    t = run([trip(cost="2000", proceeds="1500")], mapping, universe, members).trips[0]
    assert t.actual_return == D("-0.25")
    closes = {c.isin: {b.session_date: b.close for b in mapping[c.instrument].bars} for c in universe}
    for p in t.picks:  # the traded listing's closes feed features only, never its own return
        b = closes[p.isin]
        assert p.return_ratio == CALC.subtract(CALC.divide(b[session(80)], b[session(70)]), D(1))


def test_same_seed_is_identical_and_other_seeds_differ():  # spec 10.3
    mapping, universe, members = world(14)
    a = run(many(10), mapping, universe, members)
    assert a == run(many(10), mapping, universe, members) and a.to_dict() == run(many(10), mapping, universe, members).to_dict()
    b = run(many(10), mapping, universe, members, seed=8)
    assert b.input_fingerprint != a.input_fingerprint
    assert [t.alt.mean_return for t in b.trips] != [t.alt.mean_return for t in a.trips]
    assert [t.nifty.mean_return for t in b.trips] != [t.nifty.mean_return for t in a.trips]
    assert (a.alt_summary.ci_lower, a.alt_summary.ci_upper) != (b.alt_summary.ci_lower, b.alt_summary.ci_upper)


def test_trip_order_and_other_trips_never_change_a_trips_draws():  # spec 10.3
    mapping, universe, members = world(14)
    trips = many(10)
    base = run(trips, mapping, universe, members)
    assert run(list(reversed(trips)), mapping, universe, members) == base
    alone = run([trips[3]], mapping, universe, members).trips[0]
    assert alone == base.trips[3]
    extra = run(trips + [trip("ZZ", d=75, j=85)], mapping, universe, members)
    assert extra.trips[[t.trip_id for t in extra.trips].index("T03")] == base.trips[3]


def test_trips_are_sorted_by_open_close_and_id():  # spec 9
    mapping, universe, members = world(14)
    r = run([trip("B", d=72, j=80), trip("A", d=72, j=80), trip("C", d=70, j=90), trip("D", d=72, j=79)],
            mapping, universe, members)
    assert [t.trip_id for t in r.trips] == ["C", "D", "A", "B"]


def test_nifty_portfolios_hold_distinct_stocks_of_the_requested_size():  # spec 10.4
    pool = [D(i) / 100 for i in range(12)]
    portfolios = nifty_portfolio_returns(SplitMix64(1), pool, 10, 30)
    assert len(portfolios) == 30 and all(min(pool) <= p <= max(pool) for p in portfolios)
    assert portfolios == nifty_portfolio_returns(SplitMix64(1), pool, 10, 30)


def test_bootstrap_interval_is_reproducible_and_inside_the_data_range():  # spec 7
    values = [0.1, -0.2, 0.05, 0.3, -0.1, 0.02, 0.07, -0.04, 0.12, 0.0]
    a = bootstrap_mean_interval(values, SplitMix64(4), 500, D("0.95"))
    assert a == bootstrap_mean_interval(values, SplitMix64(4), 500, D("0.95"))
    assert min(values) <= a[0] <= a[1] <= max(values)
    assert bootstrap_mean_interval([0.25] * 12, SplitMix64(4), 100, D("0.95")) == (0.25, 0.25)
    assert bootstrap_mean_interval(values, SplitMix64(4), 500, D("0.5"))[0] >= a[0]
    with pytest.raises(ValueError):
        bootstrap_mean_interval([], SplitMix64(4), 100, D("0.95"))


def test_position_reads_the_interval_against_zero_only():
    assert position(0.01, 0.2) is IntervalPosition.ABOVE_ZERO
    assert position(-0.2, -0.01) is IntervalPosition.BELOW_ZERO
    assert position(-0.1, 0.1) is IntervalPosition.CONTAINS_ZERO and position(0, 0.1) is IntervalPosition.CONTAINS_ZERO


def test_summary_needs_ten_trips_for_an_interval_but_still_reports_the_means():  # spec 8, 10.5
    mapping, universe, members = world(14)
    nine = run(many(9), mapping, universe, members).alt_summary
    assert nine.ci_unavailable.reason is R.INSUFFICIENT_TRIPS and nine.ci_lower is None and nine.position is None
    assert nine.trips_used == 9 and nine.mean_excess is not None and nine.mean_percentile is not None
    ten = run(many(10), mapping, universe, members).alt_summary
    assert ten.ci_unavailable is None and ten.ci_lower <= ten.ci_upper and ten.position is not None
    assert nine.mean_unavailable is None  # an unavailable interval is not an unavailable point estimate
    none = run([], mapping, universe, members).alt_summary
    assert none.trips_used == 0 and none.mean_excess is None and none.ci_unavailable.reason is R.INSUFFICIENT_TRIPS
    assert none.mean_unavailable.reason is R.NO_AVAILABLE_TRIPS  # no point estimate at all, and it says why
    dead = run(many(3), mapping, universe, members, ca=frozenset({OWN})).nifty_summary
    # every trip stopped by the same gate: that gate is the cause, not NO_AVAILABLE_TRIPS / INSUFFICIENT_TRIPS
    assert dead.trips_used == 0 and dead.unavailable_counts == (("CORPORATE_ACTION", 3),)
    assert dead.mean_unavailable.reason is R.CORPORATE_ACTION and dead.ci_unavailable.reason is R.CORPORATE_ACTION
    assert dead.trips_evaluated == 0 and dead.survivorship_trip_count is None


def test_the_result_states_what_the_numbers_are_and_are_not():  # spec 3, 7, 9
    mapping, universe, members = world(14)
    r = run([trip()], mapping, universe, members)
    assert r.actual_return_basis == "LEDGER_PRICES_FEES_EXCLUDED"
    assert r.alternative_return_basis == "SPLIT_ADJUSTED_CLOSE_TO_CLOSE_DIVIDENDS_EXCLUDED"
    assert "OVERLAPPING_TRIPS_MAKE_INTERVAL_OPTIMISTIC" in r.limitations and "NOT_PROOF_OF_SKILL_OR_CAUSATION" in r.limitations
    prov = r.to_dict()["provenance"]
    assert prov["actual_return_basis"] == r.actual_return_basis and prov["limitations"] == list(r.limitations)
    assert prov["corporate_action_coverage"] == "DECLARED" and prov["known_corporate_action_listing_count"] == 0
    with_ca = run([trip()], mapping, universe, members, ca=frozenset({universe[0].instrument}))
    assert with_ca.to_dict()["provenance"]["known_corporate_action_listing_count"] == 1


def test_a_trip_whose_traded_listing_has_no_series_still_reports_its_actual_return_and_no_numbers():
    mapping, universe, members = world(14)
    del mapping[OWN]
    out = run([trip()], mapping, universe, members).trips[0]
    assert out.actual_return == D("0.1") and out.alt.excess is None and out.nifty.percentile is None


def test_nifty_membership_is_read_at_each_trips_own_decision_date():  # spec 2, 4
    mapping, universe, members = world(14)
    # the same 12 stocks are members only from session 75: a trip opened on 70 sees none, one opened on 76 sees them
    late = tuple(Membership(m.isin, session(75)) for m in members)
    r = run([trip("EARLY", d=70, j=80), trip("LATE", d=76, j=86)], mapping, universe, late)
    by_id = {t.trip_id: t for t in r.trips}
    assert by_id["EARLY"].nifty.unavailable.reason is R.NO_MEMBERSHIP
    assert by_id["LATE"].nifty.unavailable is None and by_id["LATE"].nifty.pool_size == 12


def test_default_parameters_run_with_500_portfolios_and_10000_replicates():  # spec 3
    mapping, universe, members = world(14)
    from app.quant.luck_test.types import LuckParameters
    r = analyze_luck(many(10), mapping, universe, members, frozenset(), LuckParameters(seed=1, as_of=RETRIEVED),
                     corporate_action_reviewed=reviewed_all(many(10), universe))
    assert r.parameters.portfolio_count == 500 and r.parameters.bootstrap_replicates == 10_000
    assert all(t.alt.portfolio_count == 500 and t.nifty.portfolio_count == 500 for t in r.trips)
    assert r.alt_summary.ci_unavailable is None and r.nifty_summary.ci_unavailable is None


@pytest.mark.parametrize("members_fn, reason", [
    (lambda m: (), R.NO_MEMBERSHIP),
    (lambda m: m[:9], R.NIFTY_POOL_TOO_SMALL),
    (lambda m: tuple(Membership(x.isin, session(90)) for x in m), R.NO_MEMBERSHIP),  # starts after the decision date
    (lambda m: tuple(Membership(x.isin, session(0), session(70)) for x in m), R.NO_MEMBERSHIP),  # ended on d (half-open)
])
def test_nifty_baseline_unavailable_reasons(members_fn, reason):  # spec 10.5
    mapping, universe, members = world(14)
    t = run([trip()], mapping, universe, members_fn(members)).trips[0]
    assert t.nifty.unavailable.reason is reason and t.nifty.excess is None and t.alt.unavailable is None


def test_membership_is_point_in_time_and_half_open():
    mapping, universe, members = world(14)
    on_d = tuple(Membership(x.isin, session(70)) for x in members)  # first day on d counts
    assert run([trip()], mapping, universe, on_d).trips[0].nifty.unavailable is None
    assert Membership(isin(1), session(1), session(5)).active_on(session(4))
    assert not Membership(isin(1), session(1), session(5)).active_on(session(5))


def test_a_member_without_an_exit_bar_is_counted_lost_and_can_make_the_pool_too_small():
    mapping, universe, members = world(14, per={k: {"length": 80} for k in (1, 2)})
    assert run([trip()], mapping, universe, members).trips[0].nifty.pool_size == 10  # 12 members, 2 lost: still enough
    mapping, universe, members = world(14, per={k: {"length": 80} for k in (1, 2, 3)})
    t = run([trip()], mapping, universe, members).trips[0]
    assert t.nifty.unavailable.reason is R.NIFTY_POOL_TOO_SMALL and t.nifty.lost_count == 3 and t.survivorship_flag


@pytest.mark.parametrize("kind, reason", [
    ("ca", R.CORPORATE_ACTION), ("noseries", R.NO_TRIP_SERIES), ("open", R.NOT_CLOSED_AT_AS_OF),
    ("gap", R.MISSING_BAR),
])
def test_trip_level_unavailable_applies_to_both_baselines(kind, reason):  # spec 8, 10.6, 10.8
    mapping, universe, members = world(14)
    ca, p_kw, t = frozenset(), {}, trip()
    if kind == "ca":
        ca = frozenset({OWN})
    elif kind == "noseries":
        del mapping[OWN]
    elif kind == "open":
        p_kw["as_of"] = RETRIEVED.replace(year=2025, month=12, day=20, hour=12)  # local date 2025-12-20 = session 80
    else:
        mapping, universe, members = world(14, own_kwargs={"skip": (80,)})
    r = run([t], mapping, universe, members, ca=ca, **p_kw)
    out = r.trips[0]
    assert out.alt.unavailable.reason is reason and out.nifty.unavailable.reason is reason and out.picks == ()
    assert out.actual_return == D("0.1") and r.alt_summary.unavailable_counts == ((reason.value, 1),)


def test_corporate_action_listing_is_excluded_as_an_alternative_and_a_member():
    mapping, universe, members = world(14)
    ca = frozenset({universe[0].instrument})
    r = run([trip()], mapping, universe, members, ca=ca).trips[0]
    assert isin(1) not in {p.isin for p in r.picks} and r.nifty.pool_size == 11


def test_fingerprint_changes_only_with_relevant_inputs():  # spec 10.9
    mapping, universe, members = world(14)
    base = run([trip()], mapping, universe, members)
    assert base.input_fingerprint == run([trip()], dict(reversed(list(mapping.items()))), tuple(reversed(universe)),
                                         tuple(reversed(members))).input_fingerprint
    stray = dict(mapping)
    stray[Instrument("UNUSEDTEST", Exchange.NSE)] = series(Instrument("UNUSEDTEST", Exchange.NSE), 4)
    assert run([trip()], stray, universe, members).input_fingerprint == base.input_fingerprint
    variants = [
        run([trip(proceeds="1101")], mapping, universe, members),
        run([trip()], mapping, universe, members[:11]),
        run([trip()], mapping, universe, members, ca=frozenset({universe[0].instrument})),
        run([trip()], mapping, universe, members, portfolio_count=51),
        run([trip()], mapping, universe, members, confidence_level=D("0.9")),
        run([trip()], world(14, per={5: {"post": lambda i, c: c + 1}})[0], universe, members),
        run([trip()], mapping, universe[:13], members),
    ]
    assert len({v.input_fingerprint for v in variants} | {base.input_fingerprint}) == len(variants) + 1


def test_to_dict_is_json_serialisable_and_carries_provenance():  # spec 9
    mapping, universe, members = world(14)
    r = run(many(10), mapping, universe, members)
    d = r.to_dict()
    text = json.dumps(d, sort_keys=True)
    assert json.loads(text) == d and set(d) == {"schema_version", "as_of", "unavailable", "provenance", "inputs", "values"}
    assert d["schema_version"] == 1 and d["as_of"] == "2026-03-10T10:00:00Z"
    assert d["provenance"]["seed"] == 7 and d["provenance"]["formula_version"] == "luck-v1"
    assert d["provenance"]["rng_version"] == "luck-rng-v1" and d["provenance"]["input_fingerprint"] == r.input_fingerprint
    assert d["inputs"]["bootstrap_replicates"] == 200 and d["inputs"]["confidence_level"] == "0.95"
    assert [t["trip_id"] for t in d["values"]["trips"]] == sorted(t["trip_id"] for t in d["values"]["trips"])
    assert set(d["values"]["summaries"]) == {"ALT", "NIFTY"}
    assert d["values"]["trips"][0]["picks"][0]["rank"] == 1


def test_results_are_frozen():
    mapping, universe, members = world(14)
    r = run([trip()], mapping, universe, members)
    with pytest.raises(Exception):
        r.trips[0].alt.excess = 1.0
    with pytest.raises(Exception):
        r.parameters = None
    assert replace(r, input_fingerprint="x").input_fingerprint == "x"


def test_input_defects_raise_and_are_never_repaired():  # spec 4, 10.7
    mapping, universe, members = world(14)
    ok = [trip()]
    with pytest.raises(LuckInputError, match="duplicate ISIN"):
        run(ok, mapping, universe + (candidate(1),), members)
    dup_instrument = universe + (type(universe[0])(universe[0].instrument, isin(99)),)
    with pytest.raises(LuckInputError, match="duplicate instrument"):
        run(ok, mapping, dup_instrument, members)
    with pytest.raises(LuckInputError, match="duplicate trip_id"):
        run(ok + ok, mapping, universe, members)
    with pytest.raises(LuckInputError, match="keyed by its own listing"):
        run(ok, {OWN: mapping[universe[0].instrument]}, universe, members)
    with pytest.raises(LuckInputError):
        run(ok, mapping, universe, members, ca={OWN})  # must be a frozenset
    with pytest.raises(LuckInputError):
        analyze_luck(ok, mapping, universe, members, frozenset(), "params")
    with pytest.raises(LuckInputError):
        analyze_luck(ok, [], universe, members, frozenset(), params())
    with pytest.raises(LuckInputError):
        analyze_luck(["not a trip"], mapping, universe, members, frozenset(), params())


@pytest.mark.parametrize("kw", [
    dict(seed=-1), dict(seed=2 ** 64), dict(seed=True), dict(formula_version="luck-v2"), dict(portfolio_count=0),
    dict(min_alternatives=11), dict(confidence_level=D("1")), dict(confidence_level=D("0")), dict(confidence_level=0.95),
    dict(bootstrap_replicates=0), dict(min_trips=0), dict(volatility_lookback=1), dict(momentum_lookback=0),
])
def test_malformed_parameters_raise(kw):
    with pytest.raises(LuckInputError):
        params(**kw)


def test_malformed_parameters_naive_as_of_raises():
    from datetime import datetime
    with pytest.raises(LuckInputError):
        params(as_of=datetime(2026, 3, 10, 10, 0))


@pytest.mark.parametrize("kw", [
    dict(cost="0"), dict(cost="-1"), dict(proceeds="0"), dict(d=80, j=70), dict(trip_id="a b"), dict(trip_id=""),
    dict(trip_isin="ine000000000"),
])
def test_malformed_trips_raise(kw):
    with pytest.raises(LuckInputError):
        trip(**kw)


def test_malformed_membership_and_candidates_raise():
    with pytest.raises(LuckInputError):
        Membership(isin(1), session(5), session(5))
    with pytest.raises(LuckInputError):
        Membership("short", session(5))
    with pytest.raises(LuckInputError):
        TripInput("T", OWN, None, session(1), session(2), 100.0, D(1))
    with pytest.raises(LuckInputError):
        type(candidate(1))(candidate(1).instrument, "bad")


def test_baseline_enum_keeps_two_distinct_results():
    mapping, universe, members = world(14)
    t = run([trip()], mapping, universe, members).trips[0]
    assert t.alt.baseline is Baseline.ALT and t.nifty.baseline is Baseline.NIFTY


@pytest.mark.parametrize("kw", [
    dict(seed=8), dict(as_of=RETRIEVED.replace(day=11)), dict(portfolio_count=51), dict(max_alternatives=9),
    dict(min_alternatives=4), dict(nifty_portfolio_size=9), dict(bootstrap_replicates=201), dict(min_trips=9),
    dict(momentum_lookback=19), dict(volatility_lookback=59), dict(confidence_level=D("0.9")),
])
def test_every_declared_parameter_is_part_of_the_fingerprint(kw):  # spec 9
    mapping, universe, members = world(14)
    assert run([trip()], mapping, universe, members, **kw).input_fingerprint != \
        run([trip()], mapping, universe, members).input_fingerprint


def test_every_declared_input_field_is_part_of_the_fingerprint():  # spec 9
    mapping, universe, members = world(14)
    base = run([trip()], mapping, universe, members).input_fingerprint
    changed = [
        run([trip(cost="1001")], mapping, universe, members),
        run([trip(d=71)], mapping, universe, members),
        run([trip(j=81)], mapping, universe, members),
        run([trip(trip_isin=None)], mapping, universe, members),
        run([trip(trip_id="T9")], mapping, universe, members),
        run([trip()], mapping, universe, (Membership(members[0].isin, session(0), session(100)),) + members[1:]),
        run([trip()], mapping, universe, members, ca=frozenset({universe[5].instrument})),
        analyze_luck([trip()], mapping, universe, members, frozenset(), params(), corporate_action_reviewed=frozenset()),
    ]
    assert len({r.input_fingerprint for r in changed} | {base}) == len(changed) + 1


def test_the_as_of_instant_can_only_remove_trips_it_never_changes_a_trips_numbers():  # spec 4 (point in time)
    mapping, universe, members = world(14)
    later = run([trip()], mapping, universe, members)
    just_after = run([trip()], mapping, universe, members, as_of=RETRIEVED.replace(year=2025, month=12, day=21, hour=12))
    assert just_after.trips == later.trips and just_after.input_fingerprint != later.input_fingerprint


# ---- corporate-action coverage is a prerequisite (spec sections 2, 4, 8) ------------------------------------------------


def undeclared(trips, mapping, universe, members, **kw):
    return analyze_luck(trips, mapping, universe, members, kw.pop("ca", frozenset()), params(**kw))  # no declaration at all


def test_undeclared_coverage_is_an_explicit_unavailable_result_never_a_valid_one():
    mapping, universe, members = world(14)
    r = undeclared(many(10), mapping, universe, members)
    reason = R.CORPORATE_ACTION_COVERAGE_UNDECLARED
    assert r.corporate_action_coverage == "UNDECLARED" and r.unavailable.reason is reason
    assert r.unavailable.reason.value == "CORPORATE_ACTION_COVERAGE_UNDECLARED"
    for t in r.trips:  # every trip is listed, none is evaluated: no draws, no picks, no exclusions, no numbers
        assert t.alt.unavailable.reason is reason and t.nifty.unavailable.reason is reason
        assert t.evaluated is False and t.lost_alternative_count is None and t.survivorship_flag is None
        assert t.picks == () and t.exclusions == () and t.alt.excess is None and t.nifty.percentile is None
        assert t.actual_return == D("0.1")  # the ledger-only return is still reported
    for s in (r.alt_summary, r.nifty_summary):  # the cause is the coverage gate, never the sample size
        assert s.trips_used == 0 and s.unavailable_counts == ((reason.value, 10),)
        assert s.mean_unavailable.reason is reason and s.ci_unavailable.reason is reason
        assert s.mean_excess is None and s.ci_lower is None and s.position is None
        assert s.trips_evaluated == 0 and s.survivorship_trip_count is None
    assert r.to_dict()["provenance"]["corporate_action_coverage"] == "UNDECLARED"
    assert r.to_dict()["provenance"]["unavailable"]["reason"] == "CORPORATE_ACTION_COVERAGE_UNDECLARED"


def test_known_actions_alone_do_not_declare_coverage():
    mapping, universe, members = world(14)
    r = undeclared([trip()], mapping, universe, members, ca=frozenset({universe[0].instrument}))
    assert r.unavailable.reason is R.CORPORATE_ACTION_COVERAGE_UNDECLARED
    assert r.trips[0].alt.unavailable.reason is R.CORPORATE_ACTION_COVERAGE_UNDECLARED  # not CORPORATE_ACTION
    assert undeclared([], mapping, universe, members).unavailable is not None  # even with nothing to evaluate


def test_undeclared_result_is_deterministic_and_its_fingerprint_differs_from_a_declared_run():
    mapping, universe, members = world(14)
    a, b = undeclared([trip()], mapping, universe, members), undeclared([trip()], mapping, universe, members)
    assert a == b and a.to_dict() == b.to_dict()
    assert a.input_fingerprint != run([trip()], mapping, universe, members).input_fingerprint
    assert undeclared([trip()], mapping, universe, members, seed=8).input_fingerprint != a.input_fingerprint


def test_declared_coverage_gives_a_valid_result_with_no_result_level_reason():
    mapping, universe, members = world(14)
    r = run([trip()], mapping, universe, members)
    assert r.corporate_action_coverage == "DECLARED" and r.unavailable is None
    assert r.trips[0].alt.unavailable is None and r.trips[0].nifty.unavailable is None


def test_an_empty_declaration_is_a_declaration_and_leaves_every_listing_unresolved():
    mapping, universe, members = world(14)
    r = run([trip()], mapping, universe, members, reviewed=frozenset())
    assert r.corporate_action_coverage == "DECLARED" and r.unavailable is None  # declared, not undeclared
    assert r.trips[0].alt.unavailable.reason is R.CORPORATE_ACTION_UNKNOWN  # ...and nothing in it is assumed clean


def test_missing_coverage_unreviewed_listings_and_known_actions_are_three_distinct_outcomes():
    mapping, universe, members = world(14)
    missing = undeclared([trip()], mapping, universe, members).trips[0].alt.unavailable.reason
    unreviewed = run([trip()], mapping, universe, members, reviewed=frozenset(c.instrument for c in universe)
                     ).trips[0].alt.unavailable.reason
    known = run([trip()], mapping, universe, members, ca=frozenset({OWN})).trips[0].alt.unavailable.reason
    assert (missing, unreviewed, known) == (R.CORPORATE_ACTION_COVERAGE_UNDECLARED, R.CORPORATE_ACTION_UNKNOWN,
                                            R.CORPORATE_ACTION)


def test_a_relevant_action_that_stays_unresolved_is_excluded_even_inside_the_declared_set():
    mapping, universe, members = world(14)
    known = universe[0].instrument  # reviewed AND known to have an action whose effect is not adjusted: still excluded
    r = run([trip()], mapping, universe, members, ca=frozenset({known})).trips[0]
    reasons = {(e.baseline.value, e.isin): e.reason.value for e in r.exclusions}
    assert reasons[("ALT", isin(1))] == "CORPORATE_ACTION" and reasons[("NIFTY", isin(1))] == "CORPORATE_ACTION"
    assert isin(1) not in {p.isin for p in r.picks} and r.nifty.pool_size == 11
    both = run([trip()], mapping, universe, members, ca=frozenset({known}),
               reviewed=reviewed_all([trip()], universe) - {known}).trips[0]  # known beats "not reviewed"
    assert {(e.baseline.value, e.isin): e.reason.value for e in both.exclusions}[("ALT", isin(1))] == "CORPORATE_ACTION"


def test_coverage_declaration_changes_the_fingerprint_but_not_other_numbers():
    mapping, universe, members = world(14)
    a = run([trip()], mapping, universe, members)
    wider = run([trip()], mapping, universe, members, reviewed=reviewed_all([trip()], universe) | {Instrument("XXTEST", Exchange.NSE)})
    assert wider.trips == a.trips and wider.input_fingerprint != a.input_fingerprint


# ---- audit fixes: summary reasons, evaluated trips, known-action count, trip-level basis, top-level unavailable ----------


def test_summary_reason_is_the_common_gate_not_the_sample_size():  # fix 1
    mapping, universe, members = world(14)
    for kw, reason in ((dict(ca=frozenset({OWN})), R.CORPORATE_ACTION),
                       (dict(reviewed=frozenset(c.instrument for c in universe)), R.CORPORATE_ACTION_UNKNOWN)):
        r = run(many(4), mapping, universe, members, **kw)
        for s in (r.alt_summary, r.nifty_summary):
            assert s.mean_unavailable.reason is reason and s.ci_unavailable.reason is reason
            assert s.unavailable_counts == ((reason.value, 4),) and s.trips_used == 0
    thin = run(many(3), *world(4))  # evaluated trips that all lack alternatives: the data gate is the cause
    assert thin.alt_summary.mean_unavailable.reason is R.INSUFFICIENT_ALTERNATIVES
    assert thin.alt_summary.ci_unavailable.reason is R.INSUFFICIENT_ALTERNATIVES and thin.alt_summary.trips_evaluated == 3


def test_mixed_gate_reasons_and_genuinely_few_trips_keep_the_sample_size_reasons():  # fix 1 (preserved behaviour)
    mapping, universe, members = world(14)
    ghost = Instrument("NOSERIES", Exchange.NSE)
    trips = [trip("A"), trip("B", instrument=ghost, trip_isin=None)]
    r = run(trips, mapping, universe, members, ca=frozenset({OWN}))
    assert {t.alt.unavailable.reason for t in r.trips} == {R.CORPORATE_ACTION, R.NO_TRIP_SERIES}
    assert r.alt_summary.mean_unavailable.reason is R.NO_AVAILABLE_TRIPS
    assert r.alt_summary.ci_unavailable.reason is R.INSUFFICIENT_TRIPS
    assert run(many(9), mapping, universe, members).alt_summary.ci_unavailable.reason is R.INSUFFICIENT_TRIPS
    assert run([], mapping, universe, members).alt_summary.mean_unavailable.reason is R.NO_AVAILABLE_TRIPS


def test_gated_trips_are_explicitly_not_evaluated_and_serialise_null_not_empty():  # fix 2
    mapping, universe, members = world(14)
    r = run([trip("GATED", instrument=Instrument("NOSERIES", Exchange.NSE), trip_isin=None), trip("OK")],
            mapping, universe, members)
    gated, ok = {t.trip_id: t for t in r.trips}["GATED"], {t.trip_id: t for t in r.trips}["OK"]
    assert gated.evaluated is False and ok.evaluated is True
    assert gated.alt.unavailable.reason is R.NO_TRIP_SERIES and gated.nifty.unavailable.reason is R.NO_TRIP_SERIES
    assert gated.lost_alternative_count is None and gated.survivorship_flag is None
    assert ok.lost_alternative_count == 0 and ok.survivorship_flag is False  # evaluated: a real zero / False
    rows = {t["trip_id"]: t for t in r.to_dict()["values"]["trips"]}
    for key in ("picks", "exclusions", "zero_variance_features", "lost_alternative_count", "survivorship_flag"):
        assert rows["GATED"][key] is None and rows["OK"][key] is not None, key
    assert rows["GATED"]["evaluated"] is False and rows["OK"]["evaluated"] is True
    for side in ("alt", "nifty"):
        assert {rows["GATED"][side][k] for k in ("portfolio_count", "pool_size", "lost_count")} == {None}
        assert rows["GATED"][side]["unavailable"]["reason"] == "NO_TRIP_SERIES"
    summary = r.to_dict()["values"]["summaries"]["ALT"]
    assert summary["trips_evaluated"] == 1 and summary["survivorship_trip_count"] == 0  # over the evaluated trip only


def test_an_evaluated_trip_with_no_picks_is_still_evaluated():  # fix 2: empty collections are not the status
    mapping, universe, members = world(14)
    t = run([trip(d=30, j=40)], mapping, universe, members).trips[0]
    assert t.alt.unavailable.reason is R.INSUFFICIENT_HISTORY and t.picks == ()
    assert t.evaluated is True and t.lost_alternative_count == 0 and t.survivorship_flag is False
    row = run([trip(d=30, j=40)], mapping, universe, members).to_dict()["values"]["trips"][0]
    assert row["evaluated"] is True and row["picks"] == [] and row["alt"]["portfolio_count"] == 0


def test_every_gate_reason_marks_the_trip_not_evaluated():  # fix 2
    mapping, universe, members = world(14)
    cases = {R.CORPORATE_ACTION: dict(ca=frozenset({OWN})),
             R.CORPORATE_ACTION_UNKNOWN: dict(reviewed=frozenset(c.instrument for c in universe)),
             R.NOT_CLOSED_AT_AS_OF: dict(as_of=RETRIEVED.replace(year=2025, month=12, day=20, hour=12))}
    for reason, kw in cases.items():
        t = run([trip()], mapping, universe, members, **kw).trips[0]
        assert t.evaluated is False and t.alt.unavailable.reason is reason, reason
    t = run([trip()], *world(14, own_kwargs={"skip": (80,)})).trips[0]
    assert t.evaluated is False and t.alt.unavailable.reason is R.MISSING_BAR
    assert undeclared([trip()], mapping, universe, members).trips[0].evaluated is False


def test_known_action_count_is_the_size_of_the_supplied_set_whatever_its_relevance():  # fix 3
    mapping, universe, members = world(14)
    irrelevant = frozenset({Instrument("IRRELEVANT", Exchange.NSE), Instrument("OTHER", Exchange.BSE)})  # not traded, not in universe
    for result, expected in (
        (undeclared([trip()], mapping, universe, members, ca=irrelevant), 2),  # undeclared: still the supplied size
        (run([trip()], mapping, universe, members, ca=irrelevant), 2),  # declared, listings irrelevant to every trip
        (run([trip()], mapping, universe, members, ca=irrelevant | {universe[0].instrument}), 3),  # one of them is relevant
        (run([trip()], mapping, universe, members), 0),
        (undeclared([trip()], mapping, universe, members), 0),
    ):
        d = result.to_dict()["provenance"]
        assert result.known_corporate_action_listing_count == expected == d["known_corporate_action_listing_count"]
        assert "corporate_action_listing_count" not in d  # the old, ambiguous name is gone
    plain, with_irrelevant = run([trip()], mapping, universe, members), run([trip()], mapping, universe, members, ca=irrelevant)
    assert with_irrelevant.trips == plain.trips  # irrelevant listings change no number...
    assert with_irrelevant.input_fingerprint != plain.input_fingerprint  # ...but they are part of the declared input


def test_trip_level_actual_return_basis_is_explicit_declared_and_undeclared():  # fix 4
    mapping, universe, members = world(14)
    for result in (run([trip()], mapping, universe, members), undeclared([trip()], mapping, universe, members)):
        d = result.to_dict()
        assert d["provenance"]["actual_return_basis"] == "LEDGER_PRICES_FEES_EXCLUDED"
        for row in d["values"]["trips"]:
            assert row["actual_return"] == "0.1" and row["actual_return_basis"] == "LEDGER_PRICES_FEES_EXCLUDED"
        assert all(t.actual_return_basis == result.actual_return_basis for t in result.trips)


def test_overall_unavailable_state_is_a_top_level_key_and_matches_provenance():  # fix 5
    mapping, universe, members = world(14)
    bad = undeclared(many(3), mapping, universe, members).to_dict()
    assert bad["unavailable"] == {"reason": "CORPORATE_ACTION_COVERAGE_UNDECLARED",
                                  "detail": "no corporate-action coverage was declared, so no listing is assumed clean"}
    assert bad["provenance"]["unavailable"] == bad["unavailable"] and bad["provenance"]["corporate_action_coverage"] == "UNDECLARED"
    for s in bad["values"]["summaries"].values():
        assert s["mean_unavailable"]["reason"] == s["ci_unavailable"]["reason"] == "CORPORATE_ACTION_COVERAGE_UNDECLARED"
    good = run(many(3), mapping, universe, members).to_dict()
    empty = run(many(3), mapping, universe, members, reviewed=frozenset()).to_dict()
    assert good["unavailable"] is None and good["provenance"]["unavailable"] is None
    assert empty["unavailable"] is None and empty["provenance"]["corporate_action_coverage"] == "DECLARED"  # declared-empty != undeclared
    assert empty["values"]["trips"][0]["alt"]["unavailable"]["reason"] == "CORPORATE_ACTION_UNKNOWN"


def test_serialisation_and_fingerprints_are_deterministic_in_both_states():  # fix 5
    mapping, universe, members = world(14)
    for build in (lambda t: run(t, mapping, universe, members), lambda t: undeclared(t, mapping, universe, members)):
        a, b = build(many(4)), build(list(reversed(many(4))))
        assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
        assert a.input_fingerprint == b.input_fingerprint and a == b
    assert undeclared(many(4), mapping, universe, members).input_fingerprint != run(many(4), mapping, universe, members).input_fingerprint
    assert run(many(4), mapping, universe, members, reviewed=frozenset()).input_fingerprint != \
        undeclared(many(4), mapping, universe, members).input_fingerprint  # declared-empty vs undeclared
