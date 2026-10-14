"""Feature 006: cost-basis fold and the three bias-v1 formulas (spec sections 4, 5, 6). Hand-computed fixtures."""
from decimal import Decimal as D

import pytest
from app.domain.enums import Exchange
from app.domain.instrument import Instrument
from bias_helpers import BSE_A, BUY, NSE_A, NSE_B, NSE_C, SELL, known, params, series, trade, validated

from app.quant.bias_cost.calculations import calculate_chasing, calculate_disposition, calculate_overtrading
from app.quant.bias_cost.context import CALC_CONTEXT as C
from app.quant.bias_cost.cost_basis import fold_positions
from app.quant.bias_cost.errors import BiasInputError, Unavailable
from app.quant.bias_cost.types import ChargeValue, FeeStatus
from app.quant.market_data.fingerprint import canonical_decimal


def _fold(trades, serieses, **kw):
    inputs = validated(trades, serieses, **kw)
    return inputs, fold_positions(inputs)


def _details(metric):
    return dict(metric.details)


# --- accounting (spec 3, 4): weighted-average, price-only, per listing -------------------------------------------------
def test_weighted_average_cost_is_110_and_gross_pnl_is_price_only():  # spec 4
    trades = [trade("T1", NSE_A, BUY, 10, 100, 0, known()), trade("T2", NSE_A, BUY, 10, 120, 1, known()),
              trade("T3", NSE_A, SELL, 5, 130, 3, known())]
    _, fold = _fold(trades, [series(NSE_A, {})])
    assert fold.sells[0].gross_pnl == D("100")  # 5 * (130 - 110); fees never enter gross P&L
    assert fold.sells[0].holding_sessions == 3 and not fold.round_trips


def test_round_trip_closes_when_flat_and_unknown_fees_do_not_change_gross_pnl():  # spec 4
    base = [trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_A, SELL, 10, 90, 2)]
    with_fees = [trade("T1", NSE_A, BUY, 10, 100, 0, known("9", "9")), trade("T2", NSE_A, SELL, 10, 90, 2, known("9", "9"))]
    _, a = _fold(base, [series(NSE_A, {})])
    _, b = _fold(with_fees, [series(NSE_A, {})])
    assert a.round_trips[0].gross_pnl == b.round_trips[0].gross_pnl == D("-100")
    assert a.round_trips[0].holding_sessions == 2


def test_oversell_in_a_listing_with_earlier_buys_is_an_input_error():  # spec 5
    with pytest.raises(BiasInputError, match="oversell"):
        _fold([trade("T1", NSE_A, BUY, 5, 100, 0), trade("T2", NSE_A, SELL, 6, 100, 1)], [series(NSE_A, {})])


def test_sell_with_no_earlier_buy_is_excluded_as_pre_window_not_an_error():  # spec 5
    _, fold = _fold([trade("T1", NSE_A, SELL, 5, 100, 1)], [series(NSE_A, {})])
    assert not fold.sells and fold.exclusions[0].subject == "T1" and "before the ledger window" in fold.exclusions[0].reason


def test_nse_and_bse_listings_of_one_symbol_are_separate_positions():  # spec 3 (listing isolation)
    trades = [trade("T1", NSE_A, BUY, 5, 100, 0), trade("T2", BSE_A, SELL, 5, 100, 1)]
    _, fold = _fold(trades, [series(NSE_A, {}), series(BSE_A, {})])
    assert not fold.sells and fold.exclusions  # the BSE sell never borrows the NSE position


# --- overtrading (spec 4): five-session boundary, signed gross, fee knownness ---------------------------------------------
def _trip(hold, sell_price, charges=None, buy_charges=None, **kw):
    trades = [trade("T1", NSE_A, BUY, 10, 100, 10, buy_charges or charges), trade("T2", NSE_A, SELL, 10, sell_price, 10 + hold, charges)]
    inputs, fold = _fold(trades, [series(NSE_A, {})], **kw)
    return calculate_overtrading(inputs, fold)


def test_five_sessions_is_short_term_and_six_is_not():  # spec 4
    metric5, facts5 = _trip(5, 95, known())
    metric6, facts6 = _trip(6, 95, known())
    assert facts5.short_term_round_trips == 1 and facts6.short_term_round_trips == 0
    assert metric5.gross_cost_inr == D("50") and metric6.gross_cost_inr == D("0")


def test_overtrading_adds_known_fees_of_all_trip_trades_once():  # spec 4
    metric, _ = _trip(2, 95, known("1", "0.5"))
    assert metric.fee_status is FeeStatus.COMPLETE and metric.fees_known == D("3.0")
    assert metric.cost_inr == D("53.0") and metric.gross_cost_inr == D("50") and not metric.is_lower_bound
    assert metric.unknown_fee_trade_count == 0


def test_profitable_short_trip_costs_only_its_fees_and_never_negative():  # spec 4 (owner formula is one-sided)
    metric, _ = _trip(2, 130, known("1", "0.5"))
    assert metric.gross_cost_inr == D("0") and metric.cost_inr == D("3.0")


def test_unknown_fees_are_counted_not_summed_and_never_zero():  # spec 3
    metric, _ = _trip(2, 95)  # both legs unknown
    assert metric.fee_status is FeeStatus.UNKNOWN and metric.fees_known is None and metric.unknown_fee_trade_count == 2
    assert metric.cost_inr == D("50") and metric.is_lower_bound


def test_partial_fees_sum_only_the_known_leg_and_are_a_lower_bound():  # spec 3
    metric, _ = _trip(2, 95, charges=ChargeValue.unknown(), buy_charges=known("2", "1"))
    assert metric.fee_status is FeeStatus.PARTIAL and metric.fees_known == D("3")
    assert metric.unknown_fee_trade_count == 1 and metric.is_lower_bound and metric.cost_inr == D("53")


def test_overtrading_with_no_closed_round_trip_is_unavailable_not_zero():  # spec 4
    inputs, fold = _fold([trade("T1", NSE_A, BUY, 5, 100, 0)], [series(NSE_A, {})])
    metric, facts = calculate_overtrading(inputs, fold)
    assert metric.cost_inr is None and isinstance(metric.unavailable, Unavailable) and facts.closed_round_trips == 0


def test_closed_trips_without_short_term_ones_cost_zero_with_complete_fee_state():  # spec 4
    metric, facts = _trip(8, 95, known())
    assert facts.closed_round_trips == 1 and facts.short_term_round_trips == 0
    assert metric.cost_inr == D("0") and metric.fee_status is FeeStatus.COMPLETE and metric.fees_known == D("0")


# --- chasing (spec 4): +10% / 20-session boundaries, forward outcome, unavailable cases -----------------------------------
def _chase_series(overrides=None):
    closes = {24: D("110"), 29: D("109.99"), 25: D("100"), 30: D("100"), 45: D("90"), 50: D("100")}
    closes.update(overrides or {})
    return series(NSE_A, closes)


def _chase_trades(chase_i=25, non_chase_i=30):
    return [trade("T1", NSE_A, BUY, 10, 100, chase_i), trade("T2", NSE_A, BUY, 10, 100, non_chase_i)]


def test_exactly_plus_ten_percent_is_a_chase_and_underperformance_is_a_positive_cost():  # spec 4
    inputs = validated(_chase_trades(), [_chase_series()])
    metric, facts = calculate_chasing(inputs)
    assert (facts.eligible_buys, facts.chase_buys) == (2, 1)  # 110 >= 100 * 1.10 chases; 109.99 does not
    # chase forward = 90/100 - 1 = -0.1, baseline (non-chase) = 100/100 - 1 = 0 -> 1000 * (0 + 0.1) = 100 > 0
    assert metric.cost_inr == D("100.0") and _details(metric)["baseline_forward_return"] == "0"


def test_outperforming_chase_is_a_negative_cost_never_clamped():  # spec 4
    inputs = validated(_chase_trades(), [_chase_series({45: D("110")})])
    metric, _ = calculate_chasing(inputs)
    assert metric.cost_inr == D("-100.0")


def test_nine_point_nine_nine_percent_run_up_is_not_a_chase():  # spec 4
    inputs = validated(_chase_trades(), [_chase_series({24: D("109.99")})])
    _, facts = calculate_chasing(inputs)
    assert facts.chase_buys == 0


def test_buy_needs_twenty_one_prior_sessions_index_20_is_ineligible_21_is_eligible():  # spec 4
    s = series(NSE_A, {20: D("100")})
    _, facts20 = calculate_chasing(validated([trade("T1", NSE_A, BUY, 1, 100, 20), trade("T2", NSE_A, BUY, 1, 100, 30)], [s]))
    _, facts21 = calculate_chasing(validated([trade("T1", NSE_A, BUY, 1, 100, 21), trade("T2", NSE_A, BUY, 1, 100, 30)], [s]))
    assert facts20.eligible_buys == 1 and facts21.eligible_buys == 2


def test_no_chase_buys_gives_zero_cost_when_a_baseline_exists():  # spec 4
    s = series(NSE_A, {})
    metric, facts = calculate_chasing(validated([trade("T1", NSE_A, BUY, 1, 100, 30)], [s]))
    assert facts.chase_buys == 0 and metric.cost_inr == D("0")


def test_no_non_chase_buy_with_forward_history_is_unavailable():  # spec 4
    metric, facts = calculate_chasing(validated([trade("T1", NSE_A, BUY, 10, 100, 25)], [_chase_series()]))
    assert metric.cost_inr is None and "baseline undefined" in metric.unavailable.reason and facts.chase_buys == 1


def test_chase_buy_without_forward_history_is_unavailable_not_zero():  # spec 4
    s = series(NSE_A, {24: D("100"), 54: D("200"), 49: D("100")})  # buy at 55: prior 200 vs base 100 -> chase; no i+20
    metric, _ = calculate_chasing(validated([trade("T1", NSE_A, BUY, 1, 100, 55), trade("T2", NSE_A, BUY, 1, 100, 30)], [s]))
    assert metric.cost_inr is None and "no chase buy has forward history" in metric.unavailable.reason


def test_future_bars_cannot_change_chase_classification_or_cost():  # spec 5 (future leakage)
    base = validated(_chase_trades(), [_chase_series()])
    changed = validated(_chase_trades(), [_chase_series({55: D("999"), 59: D("1")})])  # after every window used
    assert calculate_chasing(base)[0].cost_inr == calculate_chasing(changed)[0].cost_inr == D("100.0")
    in_between = validated(_chase_trades(), [_chase_series({26: D("999"), 44: D("1")})])  # inside the forward window
    assert calculate_chasing(in_between)[0].cost_inr == D("100.0")  # forward uses only close[i] and close[i+20]
    assert calculate_chasing(in_between)[1].chase_buys == 1


# --- disposition (spec 4): PGR/PLR, zero-P&L, lower-median H, signed cost ---------------------------------------------------
NSE_D = Instrument("DDDTEST", Exchange.NSE)


def _disposition_trades():
    return [
        trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_B, BUY, 10, 100, 0), trade("T3", NSE_C, BUY, 1, 100, 0),
        trade("T7", NSE_D, BUY, 1, 100, 0), trade("T8", NSE_D, SELL, 1, 120, 2),  # closed winning round trip, holding 2
        trade("T4", NSE_B, SELL, 5, 120, 2),  # partial winning sell, holding 2: a realised gain for PGR, never an H observation
        trade("T5", NSE_C, SELL, 1, 100, 2),  # zero P&L, closes a trip
        trade("T6", NSE_A, SELL, 5, 90, 3),  # loser, holding 3 > H
    ]


def _disposition_series(a_at_2=D("95"), b_at_3=D("110")):
    return [series(NSE_A, {2: a_at_2}), series(NSE_B, {3: b_at_3}), series(NSE_C, {}), series(NSE_D, {})]


def test_pgr_plr_counts_paper_positions_zero_pnl_excluded_and_h_is_the_winner_median():  # spec 4
    inputs, fold = _fold(_disposition_trades(), _disposition_series())
    metric, facts = calculate_disposition(inputs, fold)
    d = _details(metric)
    # day 2: B and D realised gains; C zero; A paper loss (95 < 100). day 3: A realised loss; B paper gain (110 > 100).
    # (The closed winning trip D was added when H's unit became the closed round trip; it adds one realised gain.)
    assert (d["realised_gain_positions"], d["realised_loss_positions"]) == ("2", "1")
    assert (d["paper_gain_positions"], d["paper_loss_positions"]) == ("1", "1")
    assert d["zero_pnl_positions_excluded"] == "1" and d["h_sessions"] == "2"
    assert d["pgr"] == canonical_decimal(C.divide(D(2), D(3))) and d["plr"] == "0.5"  # 2/3 and 1/2
    assert facts.pgr_minus_plr == C.subtract(C.divide(D(2), D(3)), D("0.5"))
    # losing sell held 3 > H=2: close of A at session open+H = 95, exit 90 -> (95 - 90) * 5 = +25 (it cost money)
    assert metric.cost_inr == D("25") and d["losing_sells_held_beyond_h"] == "1"


def test_disposition_cost_is_negative_when_the_price_kept_falling_never_clamped():  # spec 4
    inputs, fold = _fold(_disposition_trades(), _disposition_series(a_at_2=D("85")))
    metric, _ = calculate_disposition(inputs, fold)
    assert metric.cost_inr == D("-25")  # (85 - 90) * 5: waiting longer would not have helped


def test_pgr_minus_plr_value_uses_exact_division_not_rounding():  # spec 4
    inputs, fold = _fold(_disposition_trades(), _disposition_series(b_at_3=D("95")))
    _, facts = calculate_disposition(inputs, fold)
    # RG=1 PG=0 -> PGR=1; RL=1 PL=2 (A on day 2, B on day 3) -> PLR=1/3
    assert facts.pgr_minus_plr == C.subtract(D(1), C.divide(D(1), D(3)))


def test_lower_median_of_winner_holding_periods_is_an_integer_h():  # spec 4
    trades = [trade("T1", NSE_B, BUY, 10, 100, 0), trade("T2", NSE_B, SELL, 10, 120, 1),  # closed winning trips: holding 1
              trade("T3", NSE_C, BUY, 10, 100, 0), trade("T4", NSE_C, SELL, 10, 120, 3)]  # and holding 3
    inputs, fold = _fold(trades, [series(NSE_B, {}), series(NSE_C, {})])
    assert _details(calculate_disposition(inputs, fold)[0])["h_sessions"] == "1"  # [1, 3] -> lower median 1


def test_no_winning_sell_makes_disposition_cost_unavailable_but_keeps_the_odean_measure():  # spec 4
    trades = [trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_A, SELL, 5, 90, 3)]
    inputs, fold = _fold(trades, [series(NSE_A, {})])
    metric, facts = calculate_disposition(inputs, fold)
    assert metric.cost_inr is None and "no winning closed round trip" in metric.unavailable.reason
    assert _details(metric)["pgr_minus_plr"] != "unavailable" or facts.pgr_minus_plr is None


def test_missing_bar_for_a_paper_position_makes_disposition_unavailable():  # spec 3 (never invent data)
    short_b = series(NSE_B, [D("100")] * 3)  # no bar on session 3 for the still-held B
    trades = [trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_B, BUY, 10, 100, 0), trade("T3", NSE_A, SELL, 5, 90, 3)]
    inputs, fold = _fold(trades, [series(NSE_A, {}), short_b])
    metric, facts = calculate_disposition(inputs, fold)
    assert metric.cost_inr is None and "paper P&L unknown" in metric.unavailable.reason and facts.pgr_minus_plr is None


def test_post_sell_bars_cannot_change_the_disposition_result():  # spec 5 (future leakage)
    a = calculate_disposition(*_fold(_disposition_trades(), _disposition_series()))
    later = [series(NSE_A, {2: D("95"), 4: D("1"), 40: D("999")}), series(NSE_B, {3: D("110"), 5: D("1")}), series(NSE_C, {}), series(NSE_D, {})]
    b = calculate_disposition(*_fold(_disposition_trades(), later))
    assert a[0].cost_inr == b[0].cost_inr and a[1] == b[1]


def test_calc_params_default_to_the_owner_decisions():  # spec 3
    p = params()
    assert (p.chasing_lookback_sessions, p.forward_sessions, p.short_term_sessions, p.min_round_trips) == (20, 20, 5, 10)
    assert (p.chase_threshold, p.churner_share, p.chaser_share, p.disposition_threshold) == (
        D("0.10"), D("0.30"), D("0.40"), D("0.10"))


def test_zero_gain_opportunities_leave_pgr_and_the_difference_undefined_not_zero():  # spec 4
    inputs, fold = _fold([trade("T1", NSE_A, BUY, 10, 100, 0), trade("T2", NSE_A, SELL, 10, 90, 3)], [series(NSE_A, {})])
    metric, facts = calculate_disposition(inputs, fold)
    d = _details(metric)
    assert d["pgr"] == "unavailable" and d["pgr_minus_plr"] == "unavailable" and facts.pgr_minus_plr is None
    assert d["plr"] == "1"
