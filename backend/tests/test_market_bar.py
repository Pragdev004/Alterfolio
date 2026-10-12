"""MarketBar: validation at construction, lossless Decimal values, any provider timestamp (F1, F3, F5)."""

import dataclasses
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.quant.market_data.bar import MarketBar
from tests.market_helpers import mk_bar, ts_for

DAY = date(2026, 3, 2)
PRICE_FIELDS = ["open", "high", "low", "close", "adjusted_close"]


def test_valid_bar_keeps_every_value_exactly():
    raw = {
        "open": D("1477.4749755859375"), "high": D("1480.9000244140625"), "low": D("920.7383422851562"),
        "close": D("1477.5"), "adjusted_close": D("894.755859375"),
    }
    raw["low"] = D("920.7383422851562")
    raw["high"] = D("1480.9000244140625")
    bar = mk_bar(DAY, **raw)
    for name, value in raw.items():
        assert getattr(bar, name).as_tuple() == value.as_tuple(), name  # no rounding, no trailing-zero change


def test_there_is_no_price_accessor_because_the_basis_is_not_chosen():
    bar = mk_bar(DAY)
    for name in ("price", "value", "px", "adjusted", "basis"):
        assert not hasattr(bar, name)
    assert {f.name for f in dataclasses.fields(MarketBar)} == {
        "timestamp", "session_date", "open", "high", "low", "close", "adjusted_close", "volume"}


def test_bar_is_frozen_and_hashable_by_value():
    bar = mk_bar(DAY)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.volume = 5
    assert bar == mk_bar(DAY) and hash(bar) == hash(mk_bar(DAY))


@pytest.mark.parametrize("hour,minute", [(3, 45), (3, 30), (12, 45), (9, 44)])
def test_any_provider_timestamp_on_the_session_day_is_accepted_and_preserved(hour, minute):
    stamp = ts_for(DAY, hour, minute)
    bar = mk_bar(DAY, timestamp=stamp)
    assert bar.timestamp == stamp and bar.timestamp.utcoffset() == timedelta(0)


def test_zero_volume_is_valid():
    assert mk_bar(DAY, volume=0).volume == 0


@pytest.mark.parametrize("volume", [-1, True, False, 1.0, D(5), "5", None])
def test_invalid_volume_is_rejected(volume):
    with pytest.raises((ValueError, TypeError)):
        mk_bar(DAY, volume=volume)


def test_timestamp_must_be_aware_utc():
    with pytest.raises(ValueError):
        mk_bar(DAY, timestamp=datetime(2026, 3, 2, 3, 45))
    ist = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(ValueError):
        mk_bar(DAY, timestamp=datetime(2026, 3, 2, 9, 15, tzinfo=ist))


def test_session_date_must_be_a_plain_date():
    with pytest.raises(TypeError):
        mk_bar(DAY, session_date=datetime(2026, 3, 2))
    with pytest.raises(TypeError):
        mk_bar(DAY, session_date="2026-03-02")


@pytest.mark.parametrize("field", PRICE_FIELDS)
@pytest.mark.parametrize(
    "bad",
    [
        1.5, 100, "100", None, True,
        D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"),
        D(0), D("0.00"), D(-1), D("-0.5"),
        D(10) ** 15, D("1E+15"),
        D("1E-21"), D("1E+14"),
    ],
)
def test_prices_must_be_finite_positive_bounded_decimals_with_in_range_exponent(field, bad):
    overrides = {field: bad}
    if field in ("open", "close", "low", "high") and isinstance(bad, D) and bad.is_finite() and bad > 0:
        # keep the OHLC order valid so only the numeric guard can be responsible
        overrides = {"open": bad, "high": bad, "low": bad, "close": bad}
    with pytest.raises((ValueError, TypeError)):
        mk_bar(DAY, **overrides)


def test_exponent_boundaries_are_accepted():
    ok = D("1E-20")
    bar = mk_bar(DAY, open=ok, high=ok, low=ok, close=ok, adjusted_close=D("1E+13"))
    assert bar.open == ok and bar.adjusted_close == D("1E+13")


@pytest.mark.parametrize(
    "overrides",
    [
        dict(high=D("104")),                       # high < close
        dict(high=D("99")),                        # high < open
        dict(high=D("80")),                        # high < low
        dict(low=D("101")),                        # low > open
        dict(low=D("106")),                        # low > close
        dict(open=D("120")),                       # open > high
        dict(close=D("80")),                       # close < low
    ],
)
def test_ohlc_ordering_is_enforced(overrides):
    with pytest.raises(ValueError):
        mk_bar(DAY, **overrides)


def test_equal_ohlc_is_valid_and_adjusted_close_is_not_cross_checked_against_ohlc():
    flat = D("50")
    assert mk_bar(DAY, open=flat, high=flat, low=flat, close=flat).close == flat
    assert mk_bar(DAY, adjusted_close=D("5000")).adjusted_close == D("5000")  # above high: allowed
    assert mk_bar(DAY, adjusted_close=D("0.0001")).adjusted_close == D("0.0001")  # below low: allowed
