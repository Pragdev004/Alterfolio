"""MarketSeries, DataProvenance, local_date and point-in-time truncation (plan sections 5, 6, 8; F2, F3)."""

import dataclasses
import json
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.domain.enums import Currency
from app.quant.market_data.exchange_time import local_date
from app.quant.market_data.fingerprint import FINGERPRINT_VERSION
from app.quant.market_data.provenance import DataProvenance
from app.quant.market_data.series import MAX_BARS, MarketSeries
from tests.market_helpers import (
    IST_OFFSET, INSTRUMENT, REQUEST_END, REQUEST_START, RETRIEVED, days, mk_bar, mk_provenance, mk_series, ts_for,
)

UTC = timezone.utc
FIRST = date(2026, 3, 2)               # a Monday
DATES = days(FIRST, 5)                 # 03-02 .. 03-06
# RETRIEVED = 2026-03-10T10:00Z -> local date 2026-03-10 -> eligible dates are strictly before it.


def ist(y, m, d, hh=0, mm=0, ss=0):
    """An instant given as exchange-local (IST) wall time, as aware UTC."""
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC) - IST_OFFSET


# ---- local_date -------------------------------------------------------------------------------------------------


def test_local_date_uses_the_offset_and_flips_exactly_at_local_midnight():
    assert local_date(datetime(2026, 3, 9, 18, 29, 59, tzinfo=UTC), IST_OFFSET) == date(2026, 3, 9)
    assert local_date(datetime(2026, 3, 9, 18, 30, 0, tzinfo=UTC), IST_OFFSET) == date(2026, 3, 10)
    assert local_date(datetime(2026, 3, 9, 18, 30, 0, tzinfo=UTC), timedelta(0)) == date(2026, 3, 9)
    assert local_date(datetime(2026, 3, 9, 23, 0, tzinfo=UTC), timedelta(hours=-5)) == date(2026, 3, 9)


def test_local_date_requires_aware_instant_and_timedelta():
    with pytest.raises(ValueError):
        local_date(datetime(2026, 3, 9, 1, 0), IST_OFFSET)
    with pytest.raises(TypeError):
        local_date(datetime(2026, 3, 9, 1, 0, tzinfo=UTC), 19800)


# ---- DataProvenance ---------------------------------------------------------------------------------------------


def test_provenance_carries_fetch_facts_and_constants_but_no_coverage_verdict():
    p = mk_provenance(DATES)
    assert (p.request_start, p.request_end) == (REQUEST_START, REQUEST_END)
    assert p.first_eligible_session_date_at_fetch == DATES[0] and p.last_eligible_session_date_at_fetch == DATES[-1]
    assert p.numeric_policy == "PROVIDER_REPORTED_VERBATIM"
    assert p.close_semantics == "provider-defined"
    assert p.knowledge_basis == "AS_FETCHED_AT_RETRIEVAL"
    assert p.fingerprint_version == FINGERPRINT_VERSION
    names = {f.name for f in dataclasses.fields(DataProvenance)}
    assert not any(w in n for n in names for w in ("cover", "complete", "full", "normaliz"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.source = "x"


@pytest.mark.parametrize(
    "overrides",
    [
        dict(retrieved_at=datetime(2026, 3, 10, 10, 0)),
        dict(request_start=date(2026, 4, 1)),                                  # start after end
        dict(rows_returned=-1), dict(empty_rows_excluded=-1), dict(ineligible_bars_excluded=-1),
        dict(eligible_bars_at_fetch=-1), dict(rows_returned=True), dict(empty_rows_excluded=1.0),
        dict(eligible_bars_at_fetch=0),                                         # contradicts first/last present
        dict(first_eligible_session_date_at_fetch=None),                        # None only when zero eligible
        dict(first_eligible_session_date_at_fetch=date(2026, 3, 9)),            # first after last
        dict(source=""),
    ],
)
def test_provenance_rejects_inconsistent_fetch_facts(overrides):
    with pytest.raises((ValueError, TypeError)):
        mk_provenance(DATES, **overrides)


def test_provenance_for_zero_eligible_bars_has_no_first_or_last():
    p = mk_provenance((), rows_returned=1, ineligible_bars_excluded=1)
    assert p.eligible_bars_at_fetch == 0 and p.first_eligible_session_date_at_fetch is None


# ---- MarketSeries construction / invariants ---------------------------------------------------------------------


def test_from_eligible_bars_sets_cutoff_and_observed_through_from_retrieval():
    s = mk_series(DATES)
    assert s.cutoff == RETRIEVED and s.observed_through == date(2026, 3, 9)
    assert s.exchange_utc_offset == IST_OFFSET and s.currency is Currency.INR and s.instrument == INSTRUMENT
    assert isinstance(s.bars, tuple) and s.bar_count == 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.bars = ()


def test_there_is_no_price_accessor_on_the_series():
    s = mk_series(DATES)
    for name in ("price", "prices", "closes", "returns", "close"):
        assert not hasattr(s, name)


def test_series_never_fills_gaps():
    s = mk_series([date(2026, 3, 2), date(2026, 3, 5)])  # 03-03 and 03-04 absent
    assert [b.session_date for b in s.bars] == [date(2026, 3, 2), date(2026, 3, 5)]


def test_empty_series_is_valid_with_no_first_or_last():
    s = mk_series([])
    assert (s.bar_count, s.first_session_date, s.last_session_date) == (0, None, None)
    assert len(s.fingerprint) == 64


def test_bar_dated_on_or_after_the_retrieval_local_date_is_not_eligible():
    with pytest.raises(ValueError):
        mk_series([date(2026, 3, 9), date(2026, 3, 10)], provenance=mk_provenance([date(2026, 3, 9)]))
    with pytest.raises(ValueError):
        mk_series([date(2026, 3, 11)], provenance=mk_provenance([]))


def test_boundary_is_local_midnight_not_utc_midnight():
    # 2026-03-09T18:29:59Z is still 03-09 locally -> a 03-09 bar is NOT eligible; one minute later 03-09 becomes eligible.
    early = datetime(2026, 3, 9, 18, 29, 59, tzinfo=UTC)
    late = datetime(2026, 3, 9, 18, 30, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        mk_series([date(2026, 3, 9)], retrieved_at=early)
    assert mk_series([date(2026, 3, 9)], retrieved_at=late).last_session_date == date(2026, 3, 9)


def test_bars_must_be_a_tuple_of_market_bars_strictly_ordered_with_unique_dates():
    good = [mk_bar(d) for d in DATES]
    with pytest.raises(TypeError):
        mk_series(DATES, bars=list(good))
    with pytest.raises(TypeError):
        mk_series(DATES, bars=(good[0], "bar"))
    with pytest.raises(ValueError):
        mk_series(DATES, bars=(good[1], good[0]))                           # decreasing
    with pytest.raises(ValueError):
        mk_series(DATES, bars=(good[0], good[0]))                           # duplicate
    with pytest.raises(ValueError):
        mk_series(DATES, bars=(good[0], mk_bar(DATES[0], timestamp=ts_for(DATES[0], 12, 45))))  # same session twice


def test_session_date_must_equal_the_local_date_of_the_timestamp():
    with pytest.raises(ValueError):
        mk_series([FIRST], bars=(mk_bar(FIRST, timestamp=ts_for(FIRST, 23, 0)),))   # 23:00Z is the next IST day
    with pytest.raises(ValueError):
        mk_series([FIRST], bars=(mk_bar(FIRST, timestamp=ts_for(FIRST - timedelta(days=1), 12, 45)),))


def test_unusual_provider_timestamps_are_accepted_and_preserved():
    stamps = [ts_for(DATES[0], 3, 45), ts_for(DATES[1], 3, 30), ts_for(DATES[2], 12, 45), ts_for(DATES[3], 9, 44)]
    bars = tuple(mk_bar(d, timestamp=t) for d, t in zip(DATES[:4], stamps))
    s = mk_series(DATES[:4], bars=bars)
    assert [b.timestamp for b in s.bars] == stamps


def test_offset_must_be_a_timedelta_within_fourteen_hours():
    p = mk_provenance(DATES)
    kw = dict(instrument=INSTRUMENT, currency=Currency.INR, bars=tuple(mk_bar(d) for d in DATES), provenance=p)
    for bad in (timedelta(hours=14, seconds=1), timedelta(hours=-15), 19800, None):
        with pytest.raises((ValueError, TypeError)):
            MarketSeries.from_eligible_bars(exchange_utc_offset=bad, **kw)


def test_series_size_is_capped():
    start = date(2000, 1, 3)
    many = days(start, MAX_BARS + 1)
    retrieved = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        mk_series(many, retrieved_at=retrieved)
    assert mk_series(many[:MAX_BARS], retrieved_at=retrieved).bar_count == MAX_BARS


# ---- coverage facts (F2): facts, never a verdict ----------------------------------------------------------------


def test_partial_history_is_a_valid_series_and_requested_range_is_preserved():
    s = mk_series(DATES)  # requested 2026-01-01..2026-03-10, bars only 03-02..03-06
    assert s.first_session_date == date(2026, 3, 2) and s.last_session_date == date(2026, 3, 6) and s.bar_count == 5
    assert s.first_session_date > s.provenance.request_start
    assert (s.provenance.request_start, s.provenance.request_end) == (REQUEST_START, REQUEST_END)


def test_coverage_facts_follow_the_current_bars_after_truncation_but_fetch_facts_do_not_change():
    s = mk_series(DATES).truncated_to(ist(2026, 3, 5, 12))
    assert (s.bar_count, s.first_session_date, s.last_session_date) == (3, date(2026, 3, 2), date(2026, 3, 4))
    p = s.provenance
    assert (p.eligible_bars_at_fetch, p.last_eligible_session_date_at_fetch) == (5, date(2026, 3, 6))
    assert (p.request_start, p.request_end) == (REQUEST_START, REQUEST_END)


# ---- truncated_to: narrowing only -------------------------------------------------------------------------------


def test_truncation_keeps_only_bars_strictly_before_the_local_date_of_T():
    s = mk_series(DATES)
    t = s.truncated_to(ist(2026, 3, 4, 9, 0))
    assert [b.session_date for b in t.bars] == [date(2026, 3, 2), date(2026, 3, 3)]
    assert t.cutoff == ist(2026, 3, 4, 9, 0)
    assert t.observed_through == date(2026, 3, 3)


def test_a_bar_of_session_day_D_is_invisible_at_every_instant_of_day_D():
    s = mk_series(DATES)
    target = DATES[2]
    for minutes in range(0, 24 * 60, 7):
        t = ist(2026, 3, 4) + timedelta(minutes=minutes)
        assert target not in [b.session_date for b in s.truncated_to(t).bars], t
    assert ist(2026, 3, 4, 23, 59, 59) < ist(2026, 3, 5)
    assert target in [b.session_date for b in s.truncated_to(ist(2026, 3, 5, 0, 0, 0)).bars]
    assert target not in [b.session_date for b in s.truncated_to(ist(2026, 3, 4, 23, 59, 59)).bars]


def test_truncation_before_the_first_bar_is_a_valid_empty_series():
    t = mk_series(DATES).truncated_to(ist(2026, 3, 2, 10))
    assert t.bar_count == 0 and (t.first_session_date, t.last_session_date) == (None, None)


def test_truncation_rejects_naive_T_and_T_after_retrieved_at():
    s = mk_series(DATES)
    with pytest.raises(ValueError):
        s.truncated_to(datetime(2026, 3, 5, 12, 0))
    with pytest.raises(ValueError):
        s.truncated_to(RETRIEVED + timedelta(microseconds=1))
    with pytest.raises(ValueError):
        s.truncated_to(RETRIEVED + timedelta(days=30))
    assert s.truncated_to(RETRIEVED).bars == s.bars  # T == retrieved_at is allowed (idempotent)


def test_a_truncated_series_cannot_be_widened_again():
    t1 = mk_series(DATES).truncated_to(ist(2026, 3, 4, 9))
    with pytest.raises(ValueError):
        t1.truncated_to(ist(2026, 3, 4, 9, 0, 1))
    with pytest.raises(ValueError):
        t1.truncated_to(RETRIEVED)
    assert t1.truncated_to(ist(2026, 3, 4, 9)).bars == t1.bars  # T == cutoff is idempotent


def test_truncation_composes_and_is_idempotent():
    s = mk_series(days(FIRST, 7))
    t1, t2 = ist(2026, 3, 7, 12), ist(2026, 3, 5, 12)
    assert s.truncated_to(t1).truncated_to(t2).bars == s.truncated_to(t2).bars
    assert s.truncated_to(t2).truncated_to(t2) == s.truncated_to(t2)


def test_truncation_keeps_provenance_and_recomputes_the_fingerprint():
    s = mk_series(DATES)
    same = s.truncated_to(RETRIEVED)
    cut = s.truncated_to(ist(2026, 3, 4, 9))
    assert cut.provenance == s.provenance and cut.provenance.retrieved_at == RETRIEVED
    assert same.fingerprint == s.fingerprint
    assert cut.fingerprint != s.fingerprint
    assert cut.fingerprint == mk_series(DATES[:2]).fingerprint


def test_randomized_property_future_bars_cannot_change_a_truncated_result():
    rng = random.Random(20260412)
    start = date(2025, 11, 3)
    all_dates = [d for d in days(start, 120) if rng.random() < 0.8]
    retrieved = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
    full = mk_series([d for d in all_dates if d < date(2026, 3, 10)], retrieved_at=retrieved)
    for _ in range(200):
        t = retrieved - timedelta(seconds=rng.randrange(0, 130 * 86400))
        got = full.truncated_to(t)
        want = tuple(b for b in full.bars if b.session_date < local_date(t, IST_OFFSET))
        assert got.bars == want
        # a source with extra LATER bars (retrieved later) truncates to the identical bars for the same T
        later_retrieved = retrieved + timedelta(days=9)
        extended = mk_series(
            [d for d in all_dates if d < date(2026, 3, 10)] + days(date(2026, 3, 10), 5), retrieved_at=later_retrieved)
        assert extended.truncated_to(t).bars == got.bars


# ---- fingerprint independence from retrieval facts --------------------------------------------------------------


def test_fingerprint_ignores_retrieved_at_requested_range_and_counts():
    a = mk_series(DATES)
    b = mk_series(
        DATES, retrieved_at=RETRIEVED + timedelta(days=3),
        provenance=mk_provenance(DATES, retrieved_at=RETRIEVED + timedelta(days=3), request_start=date(2020, 1, 1),
                                 empty_rows_excluded=4, ineligible_bars_excluded=2, rows_returned=11))
    assert a.fingerprint == b.fingerprint
    assert mk_series(DATES, provenance=mk_provenance(DATES, source="other")).fingerprint != a.fingerprint


# ---- JSON form --------------------------------------------------------------------------------------------------


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_to_dict_has_the_documented_shape_exact_strings_and_no_coverage_verdict():
    s = mk_series(DATES, open=D("100.0000000000001"), close=D("105.50"))
    d = s.to_dict()
    assert set(d) == {"schema_version", "as_of", "provenance", "inputs", "values"} and d["schema_version"] == 1
    assert d["as_of"] == "2026-03-10T10:00:00Z"
    assert d["inputs"] == {
        "instrument": {"symbol": "ZZTEST", "exchange": "NSE"}, "currency": "INR", "frequency": "1d",
        "exchange_utc_offset_seconds": 19800, "request": {"start": "2026-01-01", "end": "2026-03-10"},
    }
    v = d["values"]
    assert (v["bar_count"], v["first_session_date"], v["last_session_date"]) == (5, "2026-03-02", "2026-03-06")
    assert v["bars"][0] == {
        "timestamp": "2026-03-02T03:45:00Z", "session_date": "2026-03-02", "open": "100.0000000000001",
        "high": "110", "low": "90", "close": "105.5", "adjusted_close": "104.5", "volume": 1000,
    }
    p = d["provenance"]
    assert p["fingerprint"] == s.fingerprint and p["numeric_policy"] == "PROVIDER_REPORTED_VERBATIM"
    assert p["knowledge_basis"] == "AS_FETCHED_AT_RETRIEVAL" and p["retrieved_at"] == "2026-03-10T10:00:00Z"
    assert p["request_start"] == "2026-01-01" and p["eligible_bars_at_fetch"] == 5
    assert not any(w in str(k).lower() for k in _keys(d) for w in ("cover", "complete", "full"))
    json.dumps(d)  # fully JSON-serialisable


def test_to_dict_of_a_truncated_series_reports_the_cutoff_and_current_bars():
    d = mk_series(DATES).truncated_to(ist(2026, 3, 4, 9)).to_dict()
    assert d["as_of"] == "2026-03-04T03:30:00Z"  # 09:00 IST
    assert d["values"]["bar_count"] == 2 and d["provenance"]["eligible_bars_at_fetch"] == 5
    assert d["provenance"]["retrieved_at"] == "2026-03-10T10:00:00Z"


def test_empty_series_to_dict():
    d = mk_series([]).to_dict()
    assert d["values"]["bars"] == [] and d["values"]["first_session_date"] is None
    assert d["provenance"]["first_eligible_session_date_at_fetch"] is None
