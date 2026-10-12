"""Market-series service (Feature 004 plan sections 5, 9, 11). A fake, non-Yahoo provider drives the whole path."""

import ast
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.domain.enums import Currency, Exchange
from app.domain.holding_key import HoldingKey
from app.domain.instrument import Instrument
from app.providers.market.history_port import BarFailure, BarFailureKind, HistoricalBarProvider, RawBar, RawBarBatch
from app.quant.market_data.fingerprint import compute_fingerprint
from app.quant.market_data.bar import MarketBar
from app.quant.market_data.series import MarketSeries
from app.services import market_series
from app.services.holdings import Holding
from app.services.market_series import (
    AttemptOutcome,
    MarketSeriesService,
    ResolvedSeries,
    SeriesUnavailable,
    build_series,
)

UTC = timezone.utc
IST = timedelta(hours=5, minutes=30)
NOW = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)  # local date 2026-03-10
START, END = date(2026, 1, 1), date(2026, 3, 10)
NSE = Instrument("ZZTEST", Exchange.NSE)
BSE = Instrument("ZZTEST", Exchange.BSE)
D0 = date(2026, 3, 2)


def ts(d, hh=3, mm=45):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=UTC)


def raw(d, **kw):
    fields = dict(
        timestamp=ts(d), session_date=d, open=D("100"), high=D("110"), low=D("90"), close=D("105"),
        adjusted_close=D("104.5"), volume=1000,
    )
    fields.update(kw)
    return RawBar(**fields)


def batch(instrument, bars, retrieved_at=NOW, offset=IST, rows=None, empty=0, source="fake-provider", **kw):
    fields = dict(
        instrument=instrument, bars=tuple(bars), currency=Currency.INR, source=source, retrieved_at=retrieved_at,
        exchange_utc_offset=offset, rows_returned=len(bars) + empty if rows is None else rows, empty_rows_excluded=empty,
    )
    fields.update(kw)
    return RawBarBatch(**fields)


def days(n, first=D0):
    return [first + timedelta(days=i) for i in range(n)]


class FakeProvider:
    """Not Yahoo. `answers` maps Instrument -> RawBarBatch | BarFailure | Exception to raise."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get_daily_bars(self, instrument, start, end, retrieved_at):
        self.calls.append((instrument, start, end, retrieved_at))
        answer = self.answers[instrument]
        if isinstance(answer, Exception):
            raise answer
        return answer


def service(answers, now=NOW):
    ticks = []

    def clock():
        ticks.append(1)
        return now

    provider = FakeProvider(answers)
    svc = MarketSeriesService(provider=provider, clock=clock)
    svc.ticks, svc.provider = ticks, provider
    return svc


def one(answer, listing=NSE):
    return service({listing: answer}).resolve_series([listing], START, END)


def holding(isin, *listings):
    key = HoldingKey.for_isin(isin) if isin else HoldingKey.legacy(listings[0].symbol, listings[0].exchange)
    return Holding(
        key=key, listings=tuple(listings), name=None, quantity=D(1), average_buy_price=D(1), invested_amount=D(1),
        cost_basis_complete=True,
    )


# ---- conversion, provenance, fingerprint -------------------------------------------------------------------------


def test_the_fake_provider_is_a_plain_port_implementation():
    assert isinstance(FakeProvider({}), HistoricalBarProvider)


def test_raw_bars_become_a_market_series_with_exact_values():
    exact = raw(D0, open=D("920.7383422851562"), high=D("1477.4749755859375"), low=D("894.755859375"),
                close=D("1e3"), adjusted_close=D("100.50"), volume=0)
    out = one(batch(NSE, [exact, raw(D0 + timedelta(days=1))]))
    assert isinstance(out, ResolvedSeries) and out.legacy is False
    s = out.series
    assert isinstance(s, MarketSeries) and s.instrument == NSE and s.currency is Currency.INR
    assert s.exchange_utc_offset == IST and s.cutoff == NOW and s.observed_through == date(2026, 3, 9)
    first = s.bars[0]
    assert isinstance(first, MarketBar)
    assert first.open.as_tuple() == D("920.7383422851562").as_tuple()
    assert first.close.as_tuple() == D("1e3").as_tuple() and first.adjusted_close.as_tuple() == D("100.50").as_tuple()
    assert first.volume == 0 and first.timestamp == exact.timestamp and first.session_date == D0
    assert s.to_dict()["values"]["bars"][0]["adjusted_close"] == "100.5"  # exact canonical text, no rounding


def test_provenance_is_built_from_the_actual_retrieval_facts():
    bars = [raw(d) for d in days(4)] + [raw(date(2026, 3, 10)), raw(date(2026, 3, 11))]  # last two are not eligible
    p = one(batch(NSE, bars, empty=3, source="some-source")).series.provenance
    assert (p.source, p.retrieved_at, p.request_start, p.request_end) == ("some-source", NOW, START, END)
    assert (p.rows_returned, p.empty_rows_excluded, p.ineligible_bars_excluded) == (9, 3, 2)
    assert (p.eligible_bars_at_fetch, p.first_eligible_session_date_at_fetch, p.last_eligible_session_date_at_fetch) == (
        4, D0, date(2026, 3, 5))
    assert p.numeric_policy == "PROVIDER_REPORTED_VERBATIM" and p.knowledge_basis == "AS_FETCHED_AT_RETRIEVAL"


def test_the_fingerprint_follows_the_provider_values_only():
    bars = [raw(d) for d in days(3)]
    a = one(batch(NSE, bars)).series
    expected = compute_fingerprint(
        source="fake-provider", instrument=NSE, currency=Currency.INR,
        bars=tuple(MarketBar(**{k: getattr(b, k) for k in b.__dataclass_fields__}) for b in bars),
    )
    assert a.fingerprint == expected
    later = service({NSE: batch(NSE, bars, retrieved_at=NOW + timedelta(days=1), empty=2)}, now=NOW + timedelta(days=1))
    assert later.resolve_series([NSE], date(2020, 1, 1), END).series.fingerprint == a.fingerprint  # retrieval facts excluded
    changed = [bars[0], raw(bars[1].session_date, close=D("105.01")), bars[2]]
    assert one(batch(NSE, changed)).series.fingerprint != a.fingerprint
    assert one(batch(NSE, bars, source="other")).series.fingerprint != a.fingerprint


# ---- eligibility (section 5) -------------------------------------------------------------------------------------


def test_a_bar_on_the_retrieval_local_date_is_excluded_and_counted():
    out = one(batch(NSE, [raw(date(2026, 3, 9)), raw(date(2026, 3, 10))]))
    assert [b.session_date for b in out.series.bars] == [date(2026, 3, 9)]
    assert out.series.provenance.ineligible_bars_excluded == 1 and out.series.provenance.rows_returned == 2


def test_the_boundary_is_local_midnight_of_the_batch_offset():
    bars = [raw(date(2026, 3, 9))]
    early = datetime(2026, 3, 9, 18, 29, 59, tzinfo=UTC)  # still 03-09 locally
    late = datetime(2026, 3, 9, 18, 30, 0, tzinfo=UTC)    # 03-10 locally
    assert isinstance(one(batch(NSE, bars, retrieved_at=early)), SeriesUnavailable)
    got = service({NSE: batch(NSE, bars, retrieved_at=late)}, now=late).resolve_series([NSE], START, END)
    assert [b.session_date for b in got.series.bars] == [date(2026, 3, 9)]


def test_the_same_instant_with_a_different_batch_offset_gives_a_different_cutoff():
    at = datetime(2026, 3, 9, 20, 0, tzinfo=UTC)  # 03-10 in IST, 03-09 in UTC
    day = date(2026, 3, 9)
    plain = lambda o: raw(day, timestamp=ts(day, 12, 0))  # noqa: E731
    ist = service({NSE: batch(NSE, [plain(IST)], retrieved_at=at)}, now=at).resolve_series([NSE], START, END)
    assert ist.series.bar_count == 1
    utc = service({NSE: batch(NSE, [plain(0)], retrieved_at=at, offset=timedelta(0))}, now=at)
    assert isinstance(utc.resolve_series([NSE], START, END), SeriesUnavailable)  # 03-09 is "today" at offset 0


def test_ineligible_bars_are_excluded_before_conversion_so_they_cannot_poison_the_series():
    bad_future = raw(date(2026, 3, 11), high=D("1"), low=D("2"))  # would fail MarketBar validation
    out = one(batch(NSE, [raw(date(2026, 3, 9)), bad_future]))
    assert isinstance(out, ResolvedSeries) and out.series.provenance.ineligible_bars_excluded == 1


# ---- short coverage, empty rows ----------------------------------------------------------------------------------


def test_short_coverage_is_a_partial_series_and_does_not_trigger_fallback():
    svc = service({NSE: batch(NSE, [raw(date(2026, 3, 6))]), BSE: batch(BSE, [raw(d) for d in days(5)])})
    out = svc.resolve_series([NSE, BSE], date(2025, 1, 1), END)
    assert isinstance(out, ResolvedSeries) and out.series.instrument == NSE and out.series.bar_count == 1
    assert out.series.first_session_date > out.series.provenance.request_start
    assert [c[0] for c in svc.provider.calls] == [NSE]
    assert [a.outcome for a in out.attempts] == [AttemptOutcome.USED]


def test_empty_rows_are_counted_and_never_become_bars():
    out = one(batch(NSE, [raw(D0), raw(D0 + timedelta(days=2))], empty=2, rows=4))
    p = out.series.provenance
    assert (out.series.bar_count, p.rows_returned, p.empty_rows_excluded) == (2, 4, 2)


def test_unusual_provider_timestamps_are_preserved():
    stamps = [ts(D0, 3, 45), ts(D0 + timedelta(days=1), 3, 30), ts(D0 + timedelta(days=2), 12, 45),
              ts(D0 + timedelta(days=3), 9, 44)]
    bars = [raw(D0 + timedelta(days=i), timestamp=t) for i, t in enumerate(stamps)]
    assert [b.timestamp for b in one(batch(NSE, bars)).series.bars] == stamps


# ---- listing resolution and fallback (section 9) -----------------------------------------------------------------


def test_nse_is_tried_first_then_bse_on_not_found_and_attempts_are_recorded():
    svc = service({NSE: BarFailure(BarFailureKind.NOT_FOUND, "x"), BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert isinstance(out, ResolvedSeries) and out.series.instrument == BSE
    assert [(a.listing, a.outcome) for a in out.attempts] == [(NSE, AttemptOutcome.NOT_FOUND), (BSE, AttemptOutcome.USED)]


@pytest.mark.parametrize(
    "first,outcome",
    [
        (BarFailure(BarFailureKind.INVALID_RESPONSE, "x"), AttemptOutcome.INVALID_RESPONSE),
        (batch(NSE, []), AttemptOutcome.NO_ELIGIBLE_BARS),
        (batch(NSE, [raw(date(2026, 3, 10))]), AttemptOutcome.NO_ELIGIBLE_BARS),      # only today's bar
        (batch(NSE, [raw(D0, high=D("1"), low=D("2"))]), AttemptOutcome.INVALID_BARS),  # fails MarketBar validation
        (batch(NSE, [raw(D0), raw(D0)]), AttemptOutcome.INVALID_BARS),                 # duplicate session date
        (batch(NSE, [raw(D0, session_date=D0 + timedelta(days=1))]), AttemptOutcome.INVALID_BARS),  # date != offset date
        (batch(BSE, [raw(D0)]), AttemptOutcome.INVALID_BARS),                          # answer for another listing
        (batch(NSE, [raw(D0)], exchange_utc_offset=timedelta(hours=20)), AttemptOutcome.INVALID_BARS),
        ("not an outcome", AttemptOutcome.INVALID_BARS),
    ],
)
def test_these_outcomes_fall_back_to_the_next_listing(first, outcome):
    svc = service({NSE: first, BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert isinstance(out, ResolvedSeries) and out.series.instrument == BSE
    assert out.attempts[0].outcome is outcome and out.attempts[1].outcome is AttemptOutcome.USED


def test_provider_error_does_not_fall_back():
    svc = service({NSE: BarFailure(BarFailureKind.PROVIDER_ERROR, "timeout"), BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert isinstance(out, SeriesUnavailable)
    assert [(a.listing, a.outcome) for a in out.attempts] == [(NSE, AttemptOutcome.PROVIDER_ERROR)]
    assert [c[0] for c in svc.provider.calls] == [NSE]


def test_a_provider_that_raises_is_contained_as_a_provider_error():
    svc = service({NSE: RuntimeError("boom"), BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert isinstance(out, SeriesUnavailable) and out.attempts[0].outcome is AttemptOutcome.PROVIDER_ERROR
    assert "RuntimeError" in out.attempts[0].detail and [c[0] for c in svc.provider.calls] == [NSE]


def test_every_listing_failing_is_unavailable_with_all_attempts():
    svc = service({NSE: BarFailure(BarFailureKind.NOT_FOUND, "a"), BSE: BarFailure(BarFailureKind.NOT_FOUND, "b")})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert isinstance(out, SeriesUnavailable) and len(out.attempts) == 2
    assert svc.resolve_series([], START, END) == SeriesUnavailable(attempts=(), legacy=False)


def test_there_is_no_splicing_the_series_is_one_listings_bars():
    nse_bars, bse_bars = [raw(d) for d in days(2)], [raw(d) for d in days(5)]
    svc = service({NSE: batch(NSE, nse_bars), BSE: batch(BSE, bse_bars)})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert out.series.instrument == NSE and out.series.bar_count == 2 and len(svc.provider.calls) == 1


def test_duplicate_listings_are_requested_once():
    svc = service({NSE: BarFailure(BarFailureKind.NOT_FOUND, "x")})
    svc.resolve_series([NSE, NSE], START, END)
    assert len(svc.provider.calls) == 1


def test_holding_listings_are_ordered_nse_then_bse_whatever_the_input_order():
    svc = service({NSE: BarFailure(BarFailureKind.NOT_FOUND, "x"), BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_for_holding(holding("INE000000001", BSE, NSE), START, END)
    assert [c[0] for c in svc.provider.calls] == [NSE, BSE] and out.series.instrument == BSE and out.legacy is False


def test_a_legacy_null_isin_holding_uses_its_single_listing_and_is_flagged():
    svc = service({BSE: batch(BSE, [raw(D0)]), NSE: batch(NSE, [raw(D0)])})
    out = svc.resolve_for_holding(holding(None, BSE), START, END)
    assert isinstance(out, ResolvedSeries) and out.legacy is True and out.series.instrument == BSE
    assert [c[0] for c in svc.provider.calls] == [BSE]
    failed = service({BSE: BarFailure(BarFailureKind.NOT_FOUND, "x")}).resolve_for_holding(holding(None, BSE), START, END)
    assert isinstance(failed, SeriesUnavailable) and failed.legacy is True


# ---- clock, arguments --------------------------------------------------------------------------------------------


def test_one_clock_reading_per_call_is_passed_to_every_attempt():
    svc = service({NSE: BarFailure(BarFailureKind.NOT_FOUND, "x"), BSE: batch(BSE, [raw(D0)])})
    svc.resolve_series([NSE, BSE], START, END)
    assert len(svc.ticks) == 1 and {c[3] for c in svc.provider.calls} == {NOW}
    assert [(c[1], c[2]) for c in svc.provider.calls] == [(START, END)] * 2


def test_bad_arguments_are_programming_errors_and_reach_no_provider():
    svc = service({NSE: batch(NSE, [raw(D0)])})
    with pytest.raises(ValueError):
        svc.resolve_series([NSE], END, START)
    with pytest.raises(ValueError):
        svc.resolve_series([NSE], datetime(2026, 1, 1), END)
    with pytest.raises(ValueError):
        service({NSE: batch(NSE, [raw(D0)])}, now=datetime(2026, 3, 10, 10, 0)).resolve_series([NSE], START, END)
    assert svc.provider.calls == []


def test_build_series_is_usable_directly_and_raises_on_unusable_batches():
    assert build_series(batch(NSE, [raw(D0)]), NSE, START, END, NOW).bar_count == 1
    with pytest.raises((ValueError, TypeError)):
        build_series(batch(NSE, [raw(D0)]), BSE, START, END, NOW)


# ---- the batch must echo the retrieval time the service supplied -------------------------------------------------


def test_a_batch_echoing_the_supplied_retrieved_at_is_valid():
    out = one(batch(NSE, [raw(D0)], retrieved_at=NOW))
    assert isinstance(out, ResolvedSeries) and out.series.provenance.retrieved_at == NOW and out.series.cutoff == NOW
    # the same instant written in another timezone is the same instant
    ist = timezone(IST)
    assert isinstance(one(batch(NSE, [raw(D0)], retrieved_at=NOW.astimezone(ist))), ResolvedSeries)


def test_a_later_provider_retrieved_at_cannot_make_a_future_bar_eligible():
    future_bar = raw(date(2026, 3, 12))  # after the service's local date 2026-03-10
    lying = batch(NSE, [raw(date(2026, 3, 9)), future_bar], retrieved_at=NOW + timedelta(days=5))
    svc = service({NSE: lying, BSE: batch(BSE, [raw(date(2026, 3, 9)), future_bar])})
    out = svc.resolve_series([NSE, BSE], START, END)
    # NSE's answer is rejected as an invalid batch; BSE (honest, future bar excluded by the service's clock) wins
    assert [a.outcome for a in out.attempts] == [AttemptOutcome.INVALID_BARS, AttemptOutcome.USED]
    assert [b.session_date for b in out.series.bars] == [date(2026, 3, 9)]
    assert out.series.provenance.ineligible_bars_excluded == 1 and out.series.cutoff == NOW
    alone = one(lying)
    assert isinstance(alone, SeriesUnavailable) and alone.attempts[0].outcome is AttemptOutcome.INVALID_BARS
    with pytest.raises(ValueError):
        build_series(lying, NSE, START, END, NOW)


@pytest.mark.parametrize(
    "reported",
    [NOW - timedelta(days=1), NOW - timedelta(microseconds=1), NOW + timedelta(microseconds=1), datetime(2026, 3, 10, 10, 0)],
)
def test_an_earlier_or_different_provider_retrieved_at_is_rejected(reported):
    out = one(batch(NSE, [raw(D0)], retrieved_at=reported))
    assert isinstance(out, SeriesUnavailable) and out.attempts[0].outcome is AttemptOutcome.INVALID_BARS
    assert "retrieved_at" in out.attempts[0].detail


def test_a_retrieved_at_mismatch_falls_back_like_any_invalid_batch_and_provider_error_still_does_not():
    svc = service({NSE: batch(NSE, [raw(D0)], retrieved_at=NOW - timedelta(hours=1)), BSE: batch(BSE, [raw(D0)])})
    out = svc.resolve_series([NSE, BSE], START, END)
    assert out.series.instrument == BSE and out.attempts[0].outcome is AttemptOutcome.INVALID_BARS
    stop = service({NSE: BarFailure(BarFailureKind.PROVIDER_ERROR, "x"), BSE: batch(BSE, [raw(D0)])})
    assert isinstance(stop.resolve_series([NSE, BSE], START, END), SeriesUnavailable) and len(stop.provider.calls) == 1


# ---- point-in-time -----------------------------------------------------------------------------------------------


def test_truncation_of_a_service_series_ignores_later_bars_and_later_retrievals():
    dates = days(8)
    early = one(batch(NSE, [raw(d) for d in dates])).series
    later_now = NOW + timedelta(days=5)
    extended = [raw(d) for d in dates] + [raw(d) for d in days(5, date(2026, 3, 10))]
    later = service({NSE: batch(NSE, extended, retrieved_at=later_now)}, now=later_now).resolve_series(
        [NSE], START, date(2026, 3, 15)).series
    t = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
    assert early.truncated_to(t).bars == later.truncated_to(t).bars
    assert early.truncated_to(t).fingerprint == later.truncated_to(t).fingerprint
    assert max(b.session_date for b in early.truncated_to(t).bars) < date(2026, 3, 5) + timedelta(days=1)
    with pytest.raises(ValueError):
        early.truncated_to(NOW + timedelta(seconds=1))
    assert early.truncated_to(t).provenance == early.provenance


# ---- boundaries --------------------------------------------------------------------------------------------------

SERVICE_FILE = Path(market_series.__file__)


def _imports():
    names = []
    for node in ast.walk(ast.parse(SERVICE_FILE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.append(node.module or "")
    return names


def test_the_service_reaches_providers_only_through_the_history_port():
    provider_imports = [n for n in _imports() if n.startswith("app.providers")]
    assert provider_imports and set(provider_imports) == {"app.providers.market.history_port"}
    assert not any("yahoo" in n or n.split(".")[0] == "httpx" for n in _imports())


def test_the_service_module_is_framework_free_and_otherwise_layered():
    for name in _imports():
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names or name.startswith(
            ("app.domain", "app.providers.market.history_port", "app.quant.market_data", "app.services")), name
        assert top not in {"sqlalchemy", "fastapi", "pydantic", "httpx", "starlette"}, name
        assert not name.startswith(("app.api", "app.schemas", "app.models", "app.repositories")), name


def test_quant_does_not_know_the_service_or_any_provider():
    quant = Path(market_series.__file__).resolve().parent.parent / "quant"
    for path in quant.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "app.services" not in text and "app.providers" not in text and "yahoo" not in text.lower(), path.name
