"""Feature 007 similarity, selection, eligibility and lost alternatives (spec sections 3-5, 10 rows 1, 2, 6, 7)."""
import random
from decimal import Decimal as D

import pytest

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.luck_test.analysis import analyze_luck
from app.quant.luck_test.errors import UnavailableReason as R
from app.quant.luck_test.numeric_boundary import CALC
from app.quant.luck_test.features import ListingBars, feature_vector, momentum, pool_stats, rank_candidates, volatility
from app.quant.luck_test.types import Candidate, Membership
from luck_helpers import OWN, OWN_ISIN, candidate, isin, params, reviewed_all, series, session, trip, world


def run(mapping, universe, members, trips=None, ca=frozenset(), reviewed="all", **kw):
    """Coverage is a prerequisite: by default the caller declares every traded and universe listing as reviewed."""
    trips = trips or [trip()]
    reviewed = reviewed_all(trips, universe) if reviewed == "all" else reviewed
    return analyze_luck(trips, mapping, universe, members, ca, params(**kw), corporate_action_reviewed=reviewed)


def picks_of(result):
    return [(p.rank, p.isin, p.distance) for p in result.trips[0].picks]


def test_pre_trade_view_holds_only_sessions_before_the_decision_date():  # spec 4, 10.1
    bars = ListingBars.build(series(OWN, 0))
    view = bars.before(session(70), 61)
    assert view.count == 61 and view._closes == bars.closes[9:70]  # the decision session (index 70) is not in the object
    assert view.tail(61) is not None and view.tail(62) is None
    assert view.tail(1) == (bars.closes[69],)
    assert bars.before(session(0), 61).count == 0 and bars.before(session(0), 61).tail(1) is None
    assert bars.before(session(30), 61).count == 30  # a short history is reported as short, never padded
    assert bars.close_on(session(70)) == bars.closes[70] and bars.close_on(session(500)) is None


def test_momentum_and_volatility_use_only_the_required_window():  # spec 3 (owner-approved 20 and 60 sessions)
    bars = ListingBars.build(series(OWN, 0, override={70: 9999}))  # a huge close ON d must not matter
    view = bars.before(session(70), 61)
    assert momentum(view, 20) == CALC.subtract(CALC.divide(bars.closes[69], bars.closes[49]), D(1))  # p-20 .. p
    assert momentum(bars.before(session(20), 61), 20) is None  # 20 bars is one short of the 21 closes needed
    assert momentum(bars.before(session(21), 61), 20) is not None
    assert volatility(bars.before(session(60), 61), 60) is None and volatility(view, 60) is not None
    assert feature_vector(view, 20, 60) == feature_vector(
        ListingBars.build(series(OWN, 0)).before(session(70), 61), 20, 60)


def test_volatility_is_the_sample_standard_deviation_of_sixty_simple_returns():
    closes = [D(100 + (i * 7) % 13) for i in range(61)]
    window = tuple(closes)
    from app.quant.luck_test.features import PreTradeView
    rets = [float(closes[i + 1] / closes[i] - 1) for i in range(60)]
    m = sum(rets) / 60
    expected = (sum((r - m) ** 2 for r in rets) / 59) ** 0.5  # ddof = 1
    assert volatility(PreTradeView(window, 61), 60) == pytest.approx(expected, rel=1e-12)


def test_pool_statistics_come_from_the_candidates_and_the_target_is_standardised_with_them():  # spec 3
    stats = pool_stats([(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)])
    assert stats.means == (2.0, 5.0) and stats.sds[0] == pytest.approx((2 / 3) ** 0.5)  # population (n), not sample
    assert stats.zero_variance == ("volatility",)
    z = [stats.standardise(v) for v in [(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)]]
    assert sum(a for a, _ in z) == pytest.approx(0.0) and {b for _, b in z} == {0 * 1.0}  # zero spread => z = 0, no division
    assert stats.standardise((100.0, 9.0))[1] == 0 * 1.0  # also for an outside target: no invented variation
    assert pool_stats([(2.0, 2.0)]).zero_variance == ("momentum", "volatility")
    with pytest.raises(ValueError):
        pool_stats([])


def test_ties_go_to_the_canonical_instrument_identifier_whatever_the_input_order():  # spec 5, 10.2
    z = (0.5, 0.5)
    cands = [Candidate(Instrument("ZSYM", Exchange.NSE), isin(1)), Candidate(Instrument("ASYM", Exchange.NSE), isin(9)),
             Candidate(Instrument("BSYM", Exchange.NSE), isin(5)), Candidate(Instrument("SAME", Exchange.NSE), isin(7)),
             Candidate(Instrument("SAME", Exchange.BSE), isin(8))]
    expected = [("ASYM", "NSE"), ("BSYM", "NSE"), ("SAME", "BSE"), ("SAME", "NSE"), ("ZSYM", "NSE")]  # NOT ISIN order
    for seed in range(5):
        shuffled = cands[:]
        random.Random(seed).shuffle(shuffled)
        ranked = rank_candidates((0.0, 0.0), [(c, z) for c in shuffled])
        assert [(c.instrument.symbol, c.instrument.exchange.value) for c, _ in ranked] == expected
    nearer = rank_candidates((0.0, 0.0), [(cands[0], (0.1, 0.1)), (cands[1], (0.5, 0.5))])
    assert [c.isin for c, _ in nearer] == [isin(1), isin(9)]  # distance first, the identifier only breaks ties


def test_selection_takes_at_most_ten_in_rank_order():  # spec 5
    mapping, universe, members = world(14)
    r = run(mapping, universe, members)
    picks = r.trips[0].picks
    assert len(picks) == 10 and [p.rank for p in picks] == list(range(1, 11))
    assert [p.distance for p in picks] == sorted(p.distance for p in picks)
    assert len({p.isin for p in picks}) == 10 and OWN_ISIN not in {p.isin for p in picks}


def test_universe_and_membership_order_never_change_the_selection():  # spec 10.2
    mapping, universe, members = world(14)
    base = run(mapping, universe, members)
    flipped = run(dict(reversed(list(mapping.items()))), tuple(reversed(universe)), tuple(reversed(members)))
    assert flipped.trips == base.trips and flipped.input_fingerprint == base.input_fingerprint


def test_future_bars_cannot_change_features_or_selection():  # spec 10.1 (future leakage)
    mapping, universe, members = world(14)
    base = run(mapping, universe, members)
    # every bar on or after the decision date (trip listing AND candidates) is replaced by wildly different values
    mapping2, _, _ = world(14, own_kwargs={"post": lambda i, c: c * 3 + i if i >= 70 else c},
                           per={k: {"post": lambda i, c, k=k: c * (k + 2) - i if i >= 70 else c} for k in range(1, 15)})
    changed = run(mapping2, universe, members)
    assert picks_of(changed) == picks_of(base)
    assert [p.return_ratio for p in changed.trips[0].picks] != [p.return_ratio for p in base.trips[0].picks]


def test_bars_after_the_exit_session_change_nothing():  # spec 10.1
    mapping, universe, members = world(14)
    base = run(mapping, universe, members)
    mapping2, _, _ = world(14, own_kwargs={"post": lambda i, c: c * 7 if i > 80 else c},
                           per={k: {"post": lambda i, c: c * 5 + 1 if i > 80 else c} for k in range(1, 15)})
    after = run(mapping2, universe, members)
    assert after.trips == base.trips and after.alt_summary == base.alt_summary
    assert after.input_fingerprint != base.input_fingerprint  # the series did change, the result did not


def test_ineligible_candidates_are_excluded_without_filling():  # spec 4, 10.6, 10.7
    per = {
        1: {"n": 40},  # fewer than 61 bars before d
        2: {"skip": (70,)},  # no bar on the decision date
        3: {},  # corporate action (below)
    }
    mapping, universe, members = world(14, per=per)
    r = run(mapping, universe, members, ca=frozenset({universe[2].instrument}))
    chosen = {p.isin for p in r.trips[0].picks}
    assert not chosen & {isin(1), isin(2), isin(3)} and len(chosen) == 10


def test_the_traded_stock_is_never_its_own_alternative():  # spec 4
    mapping, universe, members = world(14)
    with_self = universe + (Candidate(OWN, OWN_ISIN),)
    for t in (trip(), trip(trip_isin=None)):  # excluded by ISIN, or (no ISIN on the trip) by the listing itself
        r = run(mapping, with_self, members, trips=[t])
        assert OWN_ISIN not in {p.isin for p in r.trips[0].picks} and len(r.trips[0].picks) == 10
    same_isin_other_listing = universe + (Candidate(Instrument("OTHERLIST", Exchange.BSE), OWN_ISIN),)
    mapping2 = dict(mapping)
    mapping2[Instrument("OTHERLIST", Exchange.BSE)] = series(Instrument("OTHERLIST", Exchange.BSE), 3)
    r = run(mapping2, same_isin_other_listing, members)
    assert OWN_ISIN not in {p.isin for p in r.trips[0].picks}  # same ISIN on another listing is still the same stock


def test_a_lost_alternative_is_dropped_counted_and_flagged_never_replaced():  # spec 3, 10.6
    # candidate 1 copies the traded stock before d (distance 0, rank 1) but its series ends before the exit session
    mapping, universe, members = world(14)
    mapping[universe[0].instrument] = series(universe[0].instrument, 0, length=80)  # same closes as OWN, no bar on j=80
    r = run(mapping, universe, members)
    t = r.trips[0]
    first = t.picks[0]
    assert first.isin == isin(1) and first.return_ratio is None and first.rank == 1
    assert t.lost_alternative_count == 1 and t.survivorship_flag and t.alt.pool_size == 9
    assert len(t.picks) == 10 and sum(p.return_ratio is not None for p in t.picks) == 9
    assert t.alt.unavailable is None and r.alt_summary.survivorship_trip_count == 1


def test_too_many_lost_alternatives_make_the_baseline_unavailable():  # spec 5, 10.5
    per = {k: {"length": 80} for k in range(1, 12)}  # 11 of 14 candidates have no bar on the exit session
    mapping, universe, members = world(14, per=per)
    t = run(mapping, universe, members).trips[0]
    assert t.alt.unavailable.reason is R.INSUFFICIENT_ALTERNATIVES and t.alt.lost_count > 0 and t.alt.excess is None
    assert t.survivorship_flag


def test_fewer_than_five_eligible_alternatives_is_unavailable_not_zero():  # spec 10.5
    mapping, universe, members = world(4)
    t = run(mapping, universe, members).trips[0]
    assert t.alt.unavailable.reason is R.INSUFFICIENT_ALTERNATIVES and t.alt.excess is None and t.alt.percentile is None
    mapping5, universe5, members5 = world(5)
    assert run(mapping5, universe5, members5).trips[0].alt.unavailable is None  # exactly 5 is enough
    assert run(*world(0)).trips[0].alt.unavailable.reason is R.INSUFFICIENT_ALTERNATIVES


def test_short_history_of_the_traded_listing_is_insufficient_history():  # spec 10.6
    mapping, universe, members = world(14)
    t = run(mapping, universe, members, trips=[trip(d=30, j=40)]).trips[0]
    assert t.alt.unavailable.reason is R.INSUFFICIENT_HISTORY
    assert t.nifty.unavailable is None  # the Nifty baseline needs no similarity history


def test_equal_distance_candidates_are_ordered_by_instrument_not_by_isin_in_a_real_run():  # spec 5, 10.2
    mapping, universe, members = world(8)
    aaa, bbb = Instrument("AAATEST", Exchange.NSE), Instrument("BBBTEST", Exchange.NSE)
    extra = (Candidate(bbb, isin(21)), Candidate(aaa, isin(29)))  # BBB has the LOWER ISIN, AAA the lower symbol
    mapping = {**mapping, aaa: series(aaa, 3), bbb: series(bbb, 3)}  # identical closes => identical distance
    r = run(mapping, universe + extra, members)
    picks = {p.instrument.symbol: p for p in r.trips[0].picks}
    assert picks["AAATEST"].distance == picks["BBBTEST"].distance
    assert picks["AAATEST"].rank < picks["BBBTEST"].rank


def test_every_excluded_candidate_and_member_is_recorded_with_a_reason():  # spec 4, 10.6
    per = {1: {"n": 40}, 2: {"skip": (70,)}, 4: {"length": 80}}
    mapping, universe, members = world(14, per=per)
    del mapping[universe[4].instrument]  # candidate 5 has no series at all
    ca = frozenset({universe[2].instrument})
    members = members + (Membership(isin(77), session(0)),)  # a Nifty member that is not in the universe
    t = run(mapping, universe + (Candidate(OWN, OWN_ISIN),), members, ca=ca).trips[0]
    seen = {(e.baseline.value, e.isin): e.reason.value for e in t.exclusions}
    assert seen[("ALT", isin(1))] == "INSUFFICIENT_HISTORY" and seen[("ALT", isin(2))] == "NO_ENTRY_BAR"
    assert seen[("ALT", isin(3))] == "CORPORATE_ACTION" and seen[("ALT", isin(5))] == "NO_SERIES"
    assert seen[("ALT", OWN_ISIN)] == "SAME_AS_TRADED" and seen[("NIFTY", isin(77))] == "NOT_IN_UNIVERSE"
    assert seen[("NIFTY", isin(4))] == "NO_EXIT_BAR" and t.nifty.lost_count == 1
    assert list(t.exclusions) == sorted(t.exclusions, key=lambda e: (e.baseline.value, e.isin))
    assert not {isin(1), isin(2), isin(3), isin(5)} & {p.isin for p in t.picks}


def test_a_zero_variance_feature_is_reported_and_never_divided_by():  # spec 3
    # every candidate has the same closes before d, so neither feature has any spread across the pool
    flat = {k: {"post": lambda i, c: D(100) + D(i % 2)} for k in range(1, 15)}
    mapping, universe, members = world(14, per=flat)
    t = run(mapping, universe, members).trips[0]
    assert t.zero_variance_features == ("momentum", "volatility")
    assert all(p.distance == 0.0 for p in t.picks) and t.alt.unavailable is None
    assert [p.isin for p in t.picks] == [isin(k) for k in range(1, 11)]  # identical z: identifier order decides


def test_declared_corporate_action_coverage_excludes_unreviewed_listings_instead_of_assuming_them_clean():  # spec 4
    mapping, universe, members = world(14)
    reviewed = frozenset({OWN, *(c.instrument for c in universe[:-2])})  # the last two candidates were never reviewed
    declared = analyze_luck([trip()], mapping, universe, members, frozenset(), params(), corporate_action_reviewed=reviewed)
    full = run(mapping, universe, members)
    assert declared.corporate_action_coverage == "DECLARED" and full.corporate_action_coverage == "DECLARED"
    reasons = {(e.baseline.value, e.isin): e.reason.value for e in declared.trips[0].exclusions}
    assert reasons[("ALT", isin(13))] == "CORPORATE_ACTION_UNKNOWN" and reasons[("ALT", isin(14))] == "CORPORATE_ACTION_UNKNOWN"
    assert declared.input_fingerprint != full.input_fingerprint
    unreviewed_trip = analyze_luck([trip()], mapping, universe, members, frozenset(), params(),
                                   corporate_action_reviewed=frozenset(c.instrument for c in universe))
    t = unreviewed_trip.trips[0]
    assert t.alt.unavailable.reason is R.CORPORATE_ACTION_UNKNOWN and t.nifty.unavailable.reason is R.CORPORATE_ACTION_UNKNOWN
    with pytest.raises(Exception, match="frozenset"):
        analyze_luck([trip()], mapping, universe, members, frozenset(), params(), corporate_action_reviewed={OWN})
