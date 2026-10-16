"""Backtest calendar and point-in-time views (Feature 005 step 3)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.quant.backtest.calendar import Calendar, build_calendar, decision_instant, ordered_series, view_at
from app.quant.backtest.config import BacktestConfig, BacktestInputError, Unavailable
from app.quant.market_data.series import MarketSeries
from tests.market_helpers import IST_OFFSET, mk_bar, mk_provenance, ts_for

RETRIEVED = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)  # local date 2026-03-20 -> observed_through 2026-03-19
A = Instrument("AAA", Exchange.NSE)
B = Instrument("BBB", Exchange.NSE)


def series_for(instrument, dates, offset=IST_OFFSET, retrieved_at=RETRIEVED, currency=Currency.INR):
    dates = sorted(dates)
    return MarketSeries.from_eligible_bars(
        instrument=instrument, currency=currency, bars=tuple(mk_bar(d) for d in dates),
        exchange_utc_offset=offset, provenance=mk_provenance(dates, retrieved_at),
    )


def cfg(start=date(2026, 3, 2), end=date(2026, 3, 13)):
    return BacktestConfig(start_date=start, end_date=end, initial_cash=D("1000"), currency=Currency.INR)


def span(first, last):
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def test_common_dates_are_the_inner_join_and_dropped_dates_are_counted():
    a = series_for(A, span(date(2026, 3, 2), date(2026, 3, 6)))
    b = series_for(B, [d for d in span(date(2026, 3, 2), date(2026, 3, 6)) if d != date(2026, 3, 4)])
    cal = build_calendar([a, b], cfg(end=date(2026, 3, 6)))
    assert cal.dates == (date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 5), date(2026, 3, 6))
    assert cal.dropped_dates == (date(2026, 3, 4),)


def test_dates_outside_the_period_are_neither_traded_nor_counted_as_dropped():
    a = series_for(A, span(date(2026, 2, 20), date(2026, 3, 10)))
    b = series_for(B, span(date(2026, 3, 5), date(2026, 3, 10)))
    cal = build_calendar([a, b], cfg(start=date(2026, 3, 5), end=date(2026, 3, 10)))
    assert cal.dates[0] == date(2026, 3, 5) and cal.dropped_dates == ()


def test_empty_common_calendar_is_unavailable_not_an_error():
    a = series_for(A, [date(2026, 3, 2)])
    b = series_for(B, [date(2026, 3, 3)])
    result = build_calendar([a, b], cfg())
    assert isinstance(result, Unavailable) and "every series" in result.reason


def test_a_calendar_object_cannot_be_empty():
    with pytest.raises(BacktestInputError):
        Calendar(dates=(), dropped_dates=())


def test_series_are_sorted_by_exchange_and_symbol_regardless_of_input_order():
    a, b = series_for(A, [date(2026, 3, 2)]), series_for(B, [date(2026, 3, 2)])
    assert [s.instrument for s in ordered_series([b, a], cfg())] == [A, B]
    assert build_calendar([b, a], cfg()) == build_calendar([a, b], cfg())


@pytest.mark.parametrize("bad", [[], (), "x", None, {"a": 1}])
def test_series_must_be_a_non_empty_sequence(bad):
    with pytest.raises(BacktestInputError):
        ordered_series(bad, cfg())


def test_defective_inputs_raise():
    ok = series_for(A, [date(2026, 3, 2)])
    with pytest.raises(BacktestInputError, match="MarketSeries"):
        ordered_series([ok, object()], cfg())
    with pytest.raises(BacktestInputError, match="distinct"):
        ordered_series([ok, series_for(A, [date(2026, 3, 3)])], cfg())
    with pytest.raises(BacktestInputError, match="offset"):
        ordered_series([ok, series_for(B, [date(2026, 3, 2)], offset=timedelta(0))], cfg())
    with pytest.raises(BacktestInputError, match="no bars"):
        ordered_series([series_for(A, [])], cfg())


def test_a_series_that_does_not_cover_end_date_is_rejected_never_clipped():
    short = series_for(A, [date(2026, 3, 2)], retrieved_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc))
    with pytest.raises(BacktestInputError, match="never clipped"):
        build_calendar([short], cfg(end=date(2026, 3, 10)))  # observed_through is 2026-03-09
    assert isinstance(build_calendar([short], cfg(end=date(2026, 3, 9))), Calendar)


def test_decision_instant_is_local_midnight_ending_the_session_in_utc():
    assert decision_instant(date(2026, 3, 4), IST_OFFSET) == datetime(2026, 3, 4, 18, 30, tzinfo=timezone.utc)
    assert decision_instant(date(2026, 3, 4), timedelta(0)) == datetime(2026, 3, 5, 0, 0, tzinfo=timezone.utc)
    assert decision_instant(date(2026, 3, 4), timedelta(hours=-5)) == datetime(2026, 3, 5, 5, 0, tzinfo=timezone.utc)


def test_view_contains_bars_through_the_session_only_and_never_session_plus_one():
    s = series_for(A, span(date(2026, 3, 2), date(2026, 3, 13)))
    for d in (date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 13)):
        view = view_at([s], d)[A]
        assert view.last_session_date == d and all(b.session_date <= d for b in view.bars)


def test_view_includes_pre_start_history_and_is_read_only():
    s = series_for(A, span(date(2026, 2, 20), date(2026, 3, 13)))
    views = view_at([s], date(2026, 3, 2))
    assert views[A].first_session_date == date(2026, 2, 20)
    with pytest.raises(TypeError):
        views[B] = s  # type: ignore[index]


def test_ist_bar_stamped_on_the_previous_utc_day_belongs_to_its_local_session():
    # A bar at 2026-03-04 18:45 UTC is 2026-03-05 00:15 IST: session 2026-03-05, so it is hidden on the 4th, shown on the 5th.
    early = mk_bar(date(2026, 3, 4), timestamp=datetime(2026, 3, 3, 18, 45, tzinfo=timezone.utc))
    late = mk_bar(date(2026, 3, 5), timestamp=datetime(2026, 3, 4, 18, 45, tzinfo=timezone.utc))
    s = MarketSeries.from_eligible_bars(
        instrument=A, currency=Currency.INR, bars=(early, late), exchange_utc_offset=IST_OFFSET,
        provenance=mk_provenance([date(2026, 3, 4), date(2026, 3, 5)], RETRIEVED),
    )
    assert [b.session_date for b in view_at([s], date(2026, 3, 4))[A].bars] == [date(2026, 3, 4)]
    assert [b.session_date for b in view_at([s], date(2026, 3, 5))[A].bars] == [date(2026, 3, 4), date(2026, 3, 5)]


def test_view_beyond_the_series_cutoff_is_an_input_error():
    s = series_for(A, [date(2026, 3, 2)], retrieved_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc))
    with pytest.raises(BacktestInputError, match="cannot build the view"):
        view_at([s], date(2026, 3, 10))  # needs a cutoff at local midnight of 03-11


def test_view_is_independent_of_bars_after_the_session():
    base = span(date(2026, 3, 2), date(2026, 3, 13))
    plain = view_at([series_for(A, base)], date(2026, 3, 6))[A]
    perturbed = MarketSeries.from_eligible_bars(
        instrument=A, currency=Currency.INR,
        bars=tuple(mk_bar(d, open=D("7"), high=D("999"), close=D("8"), low=D("1")) if d > date(2026, 3, 6) else mk_bar(d) for d in base),
        exchange_utc_offset=IST_OFFSET, provenance=mk_provenance(base, RETRIEVED),
    )
    assert view_at([perturbed], date(2026, 3, 6))[A].bars == plain.bars
