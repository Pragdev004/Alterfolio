"""Feature 008 regime label: nearest rank, boundaries, history and calibration counts, leakage, gaps, degenerate cases."""

from datetime import timedelta

import pytest

from app.quant.regime_split.classify import ListingClassifier, nearest_rank
from app.quant.regime_split.errors import RegimeInputError, UnavailableReason
from app.quant.regime_split.types import Regime, RegimeParameters
from regime_helpers import bars, small, wiggle

DEFAULT = RegimeParameters()  # window 60, 33/67, 120 observations


def _classifier(n_bars: int, pool, current, params=DEFAULT):
    """A classifier whose volatility observations are fixed by hand, so the label rules are tested exactly. Bar `p` is the
    last bar before the opening date; `v(p)` is `current` and the pool is `pool` (the observations before it)."""
    window = params.volatility_window
    clf = ListingClassifier(bars([100] * n_bars), params)
    clf._vols = list(pool) + [current] + [0] * (n_bars - window - len(pool) - 1)
    return clf


def test_nearest_rank_uses_integer_ceiling_ranks():
    values = [float(i) for i in range(1, 121)]
    assert nearest_rank(values, 33) == 40.0  # ceil(39.6)
    assert nearest_rank(values, 67) == 81.0  # ceil(80.4)
    hundred = [float(i) for i in range(1, 101)]
    assert (nearest_rank(hundred, 33), nearest_rank(hundred, 67)) == (33.0, 67.0)  # exact: no rounding up
    assert (nearest_rank([5.0, 6.0, 7.0], 33), nearest_rank([5.0, 6.0, 7.0], 67)) == (5.0, 7.0)


def test_boundaries_are_inclusive_at_both_thresholds():
    pool = [float(i) for i in range(1, 121)]  # P33 = 40, P67 = 81
    # B = 181 bars before d (p = 180), so d is bar 181; one more bar keeps `close_on(d)` defined.
    labels = {}
    for current in (39.9, 40.0, 40.1, 80.9, 81.0, 81.1):
        label = _classifier(182, pool, current).label(bars([100] * 182).dates[181])
        labels[current] = label.regime
        assert (label.low_threshold, label.high_threshold, label.calibration_count) == (40.0, 81.0, 120)
    assert labels == {39.9: Regime.LOW, 40.0: Regime.LOW, 40.1: Regime.NORMAL, 80.9: Regime.NORMAL, 81.0: Regime.HIGH,
                      81.1: Regime.HIGH}


def test_calibration_needs_120_prior_observations_not_counting_the_current_one():
    pool = [float(i) for i in range(1, 121)]
    d = bars([100] * 182).dates
    ok = _classifier(182, pool, 50.0).label(d[181])  # B = 181 -> 181 - 61 = 120
    assert ok.regime is Regime.NORMAL and ok.calibration_count == 120
    short = _classifier(182, pool[:119], 50.0).label(d[180])  # B = 180 -> 119
    assert short.regime is None and short.unavailable.reason is UnavailableReason.INSUFFICIENT_CALIBRATION
    assert short.volatility == 50.0 and short.low_threshold is None  # the current value is reported, no threshold invented


def test_history_needs_61_closes_before_the_opening_date():
    b = bars([100] * 70)
    clf = ListingClassifier(b, DEFAULT)
    too_short = clf.label(b.dates[60])  # B = 60
    assert too_short.unavailable.reason is UnavailableReason.INSUFFICIENT_HISTORY and too_short.volatility is None
    enough = clf.label(b.dates[61])  # B = 61: computable, but no calibration yet
    assert enough.unavailable.reason is UnavailableReason.INSUFFICIENT_CALIBRATION and enough.calibration_count is None
    assert enough.volatility == 0.0  # zero volatility is a valid observation, not a missing one


def test_missing_bar_on_the_opening_date():
    b = bars([100] * 200, step=2)
    label = ListingClassifier(b, DEFAULT).label(b.dates[190] + timedelta(days=1))  # bars are every 2nd day
    assert label.unavailable.reason is UnavailableReason.MISSING_BAR


def test_equal_thresholds_are_degenerate_never_a_label():
    flat = ListingClassifier(bars([100] * 40), small())  # all observations are 0.0
    label = flat.label(bars([100] * 40).dates[30])
    assert label.regime is None and label.unavailable.reason is UnavailableReason.DEGENERATE_THRESHOLDS
    assert label.low_threshold == label.high_threshold == 0.0 and label.volatility == 0.0
    cycle = ListingClassifier(bars([100, 110] * 30), small())  # identical windows give identical volatilities
    assert cycle.label(bars([100, 110] * 30).dates[40]).unavailable.reason is UnavailableReason.DEGENERATE_THRESHOLDS


def test_a_rising_and_a_falling_volatility_series_label_high_and_low():
    rising = bars(wiggle(60, lambda i: 1 + i / 4))
    falling = bars(wiggle(60, lambda i: 16 - i / 4))
    assert ListingClassifier(rising, small()).label(rising.dates[50]).regime is Regime.HIGH
    assert ListingClassifier(falling, small()).label(falling.dates[50]).regime is Regime.LOW


def test_nothing_on_or_after_the_opening_date_changes_the_label():
    closes = wiggle(80, lambda i: 1 + (i * 7) % 5)
    base = ListingClassifier(bars(closes), small()).label(bars(closes).dates[50])
    for cut in (50, 51, 79):
        altered = closes[:cut] + [c * 3 for c in closes[cut:]]
        assert ListingClassifier(bars(altered), small()).label(bars(altered).dates[50]) == base
    before = closes[:49] + [closes[49] * 2] + closes[50:]
    assert ListingClassifier(bars(before), small()).label(bars(before).dates[50]) != base  # control: the past matters


def test_each_listing_is_calibrated_on_its_own_history_only():
    quiet, loud = bars(wiggle(60, lambda i: 1)), bars(wiggle(60, lambda i: 1 + i % 9))
    a = ListingClassifier(loud, small()).label(loud.dates[50])
    alone = ListingClassifier(loud, small()).label(loud.dates[50])
    ListingClassifier(quiet, small()).label(quiet.dates[50])  # labelling another listing never changes this one
    assert a == alone and a.calibration_count == 44  # 50 bars before d, window 5: 50 - 5 - 1


def test_gaps_are_never_filled_bars_are_counted_not_calendar_days():
    b = bars(wiggle(40, lambda i: 1 + (i * 3) % 4), step=3)
    label = ListingClassifier(b, small()).label(b.dates[30])
    assert label.calibration_count == 24  # 30 bars before d: 30 - 5 - 1
    dense = bars(wiggle(40, lambda i: 1 + (i * 3) % 4), step=1)
    assert ListingClassifier(dense, small()).label(dense.dates[30]) == label


def test_a_non_positive_close_is_an_input_error_not_a_skipped_observation():
    closes = wiggle(40)
    closes[20] = 0
    with pytest.raises(RegimeInputError, match="positive"):
        ListingClassifier(bars(closes), small()).label(bars(closes).dates[30])


def test_parameter_validation():
    for bad in (dict(volatility_window=1), dict(low_percentile=67, high_percentile=33), dict(low_percentile=0),
                dict(high_percentile=100), dict(min_calibration=0), dict(min_trips_per_regime=True),
                dict(formula_version="regime-v2")):
        with pytest.raises(RegimeInputError):
            RegimeParameters(**bad)
