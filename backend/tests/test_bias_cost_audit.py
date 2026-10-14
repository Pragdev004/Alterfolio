"""Feature 006 post-implementation audit: exact-precision defects, presentation rounding, availability and coverage gaps."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from bias_helpers import BSE_A, BUY, NSE_A, NSE_B, NSE_C, SELL, known, params, series, session, trade, validated

from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from app.quant.bias_cost.analysis import analyze_biases
from app.quant.bias_cost.calculations import calculate_chasing, calculate_disposition
from app.quant.bias_cost.context import CALC_CONTEXT as C
from app.quant.bias_cost.cost_basis import fold_positions
from app.quant.bias_cost.errors import BiasInputError
from app.quant.bias_cost.presentation import PRESENTATION_QUANTUM, present_inr
from app.quant.bias_cost.types import BiasKind, BiasMetric
from app.quant.market_data.fingerprint import canonical_decimal


def _decimals_after_point(value: D) -> int:
    return max(0, -value.as_tuple().exponent)


# --- exact internal precision vs presentation (spec 2, 3) ---------------------------------------------------------------
def test_non_terminating_average_cost_does_not_break_the_fee_consistency_check():  # spec 2 (audit defect)
    # average cost = (100 + 2 * 100.5) / 3 is non-terminating, so gross P&L carries ~60 digits; adding fees must stay exact.
    trades = [trade("T1", NSE_A, BUY, 1, 100, 0, known()), trade("T2", NSE_A, BUY, 2, "100.5", 0, known()),
              trade("T3", NSE_A, SELL, 3, "90.1", 2, known())]
    metric = next(r.metric for r in analyze_biases(trades, {NSE_A: series(NSE_A, {})}, params()).results
                  if r.metric.bias is BiasKind.OVERTRADING)
    assert metric.cost_inr == C.add(metric.gross_cost_inr, metric.fees_known)
    assert _decimals_after_point(metric.gross_cost_inr) > 6 or metric.gross_cost_inr == D("0")


def test_chasing_baseline_is_the_exact_mean_not_a_28_digit_rounding():  # spec 2 (audit defect)
    closes = {30: D("3"), 50: D("1"), 31: D("7"), 51: D("1")}
    trades = [trade("T1", NSE_A, BUY, 1, 100, 30), trade("T2", NSE_A, BUY, 1, 100, 31)]
    metric, _ = calculate_chasing(validated(trades, [series(NSE_A, closes)]))
    r1, r2 = C.subtract(C.divide(D(1), D(3)), D(1)), C.subtract(C.divide(D(1), D(7)), D(1))
    assert dict(metric.details)["baseline_forward_return"] == canonical_decimal(C.divide(C.add(r1, r2), D(2)))


def test_internal_cost_keeps_full_precision_and_only_presentation_rounds_to_six_places():  # spec 2
    closes = {21: D("110"), 22: D("3"), 42: D("1"), 31: D("7"), 51: D("1")}
    trades = [trade("T1", NSE_A, BUY, 10, 100, 22), trade("T2", NSE_A, BUY, 10, 100, 31)]
    metric, _ = calculate_chasing(validated(trades, [series(NSE_A, closes)]))
    assert metric.cost_inr is not None and _decimals_after_point(metric.cost_inr) > 6  # internal value is not rounded
    shown = present_inr(metric.cost_inr)
    assert shown.as_tuple().exponent == -6 and shown == metric.cost_inr.quantize(PRESENTATION_QUANTUM, context=C)
    assert metric.cost_inr != shown  # presenting does not alter the stored value


def test_present_inr_rounds_half_even_keeps_sign_and_never_touches_none_semantics():  # spec 2
    assert present_inr(D("0.1234565")) == D("0.123456") and present_inr(D("0.1234575")) == D("0.123458")
    assert present_inr(D("-0.1234565")) == D("-0.123456") and present_inr(D("-5")) == D("-5.000000")
    assert present_inr(D("1E+20")) == D("100000000000000000000.000000")
    with pytest.raises(BiasInputError):
        present_inr(None)
    with pytest.raises(BiasInputError):
        present_inr(D("NaN"))
    with pytest.raises(BiasInputError):
        present_inr(1.5)


def test_metric_still_accepts_an_exact_value_finer_than_six_places():  # spec 2 (owner decision 2026-10-14)
    assert BiasMetric(BiasKind.CHASING, "bias-v1", D("0.1234567891"), None).cost_inr == D("0.1234567891")


# --- non-monotonic sessions (spec 5) ----------------------------------------------------------------------------------------
def test_session_dates_going_backwards_across_listings_are_rejected():  # spec 5
    ahead = series(NSE_B, {}, offset=timedelta(hours=14))  # 10:00 UTC is already the NEXT local date here
    behind = series(NSE_A, {})  # 11:00 UTC is still the previous local date
    trades = [trade("T1", NSE_B, BUY, 1, 100, 3, hour=10), trade("T2", NSE_A, BUY, 1, 100, 3, hour=11)]
    inputs = validated(trades, [ahead, behind])
    assert [dict(inputs.sessions)[t] for t in ("T1", "T2")] == [session(4), session(3)]
    with pytest.raises(BiasInputError, match="go backwards"):
        fold_positions(inputs)


# --- ISIN: listings are intentionally separate positions (spec 3, 7) -----------------------------------------------------------
def test_same_isin_on_two_listings_is_never_merged_into_one_position():  # spec 7 (out of scope: ISIN merging)
    isin = "INE000A01010"
    import dataclasses

    buy = dataclasses.replace(trade("T1", NSE_A, BUY, 5, 100, 0), isin=isin)
    sell = dataclasses.replace(trade("T2", BSE_A, SELL, 5, 110, 2), isin=isin)
    inputs = validated([buy, sell], [series(NSE_A, {}), series(BSE_A, {})])
    fold = fold_positions(inputs)
    assert not fold.sells and not fold.round_trips  # the BSE sell cannot close the NSE position
    assert [e.subject for e in fold.exclusions] == ["T2"]


# --- missing series: which metrics depend on it (spec 3) -------------------------------------------------------------------------
def _missing_series_analysis():
    trades = [trade("T1", NSE_A, BUY, 5, 100, 0), trade("T2", NSE_A, SELL, 5, 110, 3), trade("T3", BSE_A, BUY, 5, 100, 0)]
    return analyze_biases(trades, {NSE_A: series(NSE_A, {})}, params())  # BSE listing has trades but no series


def test_a_listing_without_a_series_blocks_every_metric_because_each_pools_all_listings():  # spec 3 (owner decision: strict completeness)
    analysis = _missing_series_analysis()
    assert [r.metric.cost_inr for r in analysis.results] == [None, None, None]
    assert all("AAATEST.BSE" in r.metric.unavailable.reason for r in analysis.results)
    assert [p.instrument for r in analysis.results for p in r.metric.listings] == [NSE_A] * 3  # only data actually loaded


def test_a_series_for_a_listing_with_no_trades_is_ignored():  # spec 3
    trades = [trade("T1", NSE_A, BUY, 5, 100, 0), trade("T2", NSE_A, SELL, 5, 110, 3)]
    with_extra = analyze_biases(trades, {NSE_A: series(NSE_A, {}), NSE_B: series(NSE_B, {})}, params())
    without = analyze_biases(trades, {NSE_A: series(NSE_A, {})}, params())
    assert [r.metric.cost_inr for r in with_extra.results] == [r.metric.cost_inr for r in without.results]
    assert all(p.instrument == NSE_A for r in with_extra.results for p in r.metric.listings)


# --- formula boundaries that were implemented but not pinned (spec 4) -------------------------------------------------------------
def test_forward_window_boundary_bar_59_is_available_and_bar_60_is_not():  # spec 4
    trades = [trade("T1", NSE_A, BUY, 1, 100, 39), trade("T2", NSE_A, BUY, 1, 100, 40)]  # 39+20=59 exists; 40+20=60 does not
    metric, facts = calculate_chasing(validated(trades, [series(NSE_A, {})]))
    assert facts.eligible_buys == 2 and dict(metric.details)["non_chase_buys_with_forward"] == "1"


def test_position_priced_exactly_at_cost_on_a_sell_day_is_a_zero_pnl_position():  # spec 4
    trades = [trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_B, BUY, 10, 100, 0), trade("T3", NSE_B, SELL, 5, 120, 2)]
    inputs = validated(trades, [series(NSE_A, {}), series(NSE_B, {})])  # A closes at 100 on the sell day: paper P&L is 0
    d = dict(calculate_disposition(inputs, fold_positions(inputs))[0].details)
    assert d["zero_pnl_positions_excluded"] == "1" and d["paper_gain_positions"] == d["paper_loss_positions"] == "0"


def test_two_sells_of_one_listing_on_one_day_count_as_one_realised_position_by_their_sum():  # spec 4
    trades = [trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_A, SELL, 2, 120, 2, hour=5), trade("T3", NSE_A, SELL, 2, 90, 2, hour=6)]
    inputs = validated(trades, [series(NSE_A, {})])
    d = dict(calculate_disposition(inputs, fold_positions(inputs))[0].details)  # +40 and -20 -> one realised gain of +20
    assert (d["realised_gain_positions"], d["realised_loss_positions"]) == ("1", "0")


def test_future_bars_cannot_change_overtrading_or_any_availability():  # spec 5
    trades = [trade("T1", NSE_A, BUY, 10, 100, 10, known()), trade("T2", NSE_A, SELL, 10, 95, 12, known())]
    base = analyze_biases(trades, {NSE_A: series(NSE_A, {})}, params())
    later = analyze_biases(trades, {NSE_A: series(NSE_A, {13: D("1"), 59: D("999")})}, params())
    assert [r.metric.cost_inr for r in base.results] == [r.metric.cost_inr for r in later.results]
    assert base.profile == later.profile


def test_unknown_ids_in_series_mapping_and_exchange_enum_are_distinct_listings():  # spec 3
    assert Instrument("AAATEST", Exchange.NSE) != Instrument("AAATEST", Exchange.BSE)


# --- H = lower median of winner holding sessions (owner decision, final) ---------------------------------------------------------
def _h_case(winner_holdings):
    """One closed winning round trip per given holding (its own listing, bought at 0, sold at that session); A: loser held 2."""
    trades = [trade("TA", NSE_A, BUY, 10, 100, 0), trade("LA", NSE_A, SELL, 5, 90, 2)]
    serieses = [series(NSE_A, {1: D("98")})]
    for k, hold in enumerate(winner_holdings):
        listing = Instrument(f"W{k}TEST", Exchange.NSE)
        trades += [trade(f"WB{k}", listing, BUY, 2, 100, 0), trade(f"WS{k}", listing, SELL, 2, 120, hold)]
        serieses.append(series(listing, {}))
    inputs = validated(trades, serieses)
    return calculate_disposition(inputs, fold_positions(inputs))[0]


def test_even_winner_count_uses_the_lower_middle_value_not_the_average():  # spec 3 (owner decision)
    metric = _h_case([1, 2])  # sorted [1, 2]: lower = 1, conventional median = 1.5, upper = 2
    assert dict(metric.details)["h_sessions"] == "1"
    assert metric.cost_inr == D("40")  # loser held 2 > 1: (close at open+1 = 98 - exit 90) * 5
    # With H = 2 (upper middle, or 1.5 rounded up) the loser would not count and the cost would be 0, so the rule matters.


def test_odd_winner_count_uses_the_middle_value():  # spec 3 (owner decision)
    metric = _h_case([1, 2, 4])  # sorted [1, 2, 4]: middle = 2
    assert dict(metric.details)["h_sessions"] == "2"
    assert metric.cost_inr == D("0") and dict(metric.details)["losing_sells_held_beyond_h"] == "0"  # held 2 is not > 2


def test_four_winners_use_the_second_value_and_one_winner_uses_itself():  # spec 3 (owner decision)
    assert dict(_h_case([1, 2, 3, 4]).details)["h_sessions"] == "2"  # lower of the two middle values, [1,2,3,4] -> 2
    assert dict(_h_case([3]).details)["h_sessions"] == "3"


def test_h_counts_each_closed_winning_round_trip_once_not_each_partial_winning_sell():  # spec 3 (owner decision, final)
    b = [trade("B0", NSE_B, BUY, 20, 100, 0)]
    b += [trade(f"BS{h}", NSE_B, SELL, 2, 120, 1, hour=5 + h) for h in range(3)]  # three partial winning sells, holding 1
    b += [trade("BS9", NSE_B, SELL, 14, 120, 6)]  # closes the round trip: one closed winner, holding 6
    e = [trade("E0", NSE_C, BUY, 1, 100, 0), trade("E1", NSE_C, SELL, 1, 120, 4)]  # a second closed winner, holding 4
    a = [trade("A0", NSE_A, BUY, 10, 100, 0), trade("A1", NSE_A, SELL, 5, 90, 3)]  # loser held 3 sessions, never closed
    inputs = validated(b + e + a, [series(NSE_A, {1: D("98")}), series(NSE_B, {}), series(NSE_C, {})])
    fold = fold_positions(inputs)
    sell_level = sorted(s.holding_sessions for s in fold.sells if s.gross_pnl > 0)
    assert sell_level == [1, 1, 1, 4, 6] and sell_level[(len(sell_level) - 1) // 2] == 1  # the OLD unit would give H = 1
    metric = calculate_disposition(inputs, fold)[0]
    d = dict(metric.details)
    assert d["h_sessions"] == "4"  # closed winning trips [4, 6]: lower median 4
    assert d["losing_sells_held_beyond_h"] == "0" and metric.cost_inr == D("0")  # held 3 is NOT beyond 4 (it would be beyond 1)


def test_an_unclosed_winning_position_never_provides_an_h_observation():  # spec 3 (owner decision, final)
    trades = [trade("B0", NSE_B, BUY, 10, 100, 0), trade("B1", NSE_B, SELL, 5, 120, 2)]
    inputs = validated(trades, [series(NSE_B, {})])
    metric, facts = calculate_disposition(inputs, fold_positions(inputs))
    assert metric.cost_inr is None and "no winning closed round trip" in metric.unavailable.reason
