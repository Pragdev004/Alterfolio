"""Yahoo daily-bar adapter (Feature 004 plan section 4, F1-F6). Mocked HTTP only; synthetic ZZ symbols and prices."""

import dataclasses
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.providers.market.history_port import (
    BarFailure,
    BarFailureKind,
    HistoricalBarProvider,
    RawBar,
    RawBarBatch,
)
from app.providers.market.yahoo import YahooProvider

NOW = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
NSE = Instrument("ZZTEST", Exchange.NSE)
BSE = Instrument("ZZTEST", Exchange.BSE)
START, END = date(2026, 3, 1), date(2026, 3, 3)
IST = timedelta(hours=5, minutes=30)
UTC = timezone.utc


def epoch(y, m, d, hh=3, mm=45):
    return int(datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp())


def row(ts, o="100", h="110", l="90", c="105", v="1000", adj="104.5"):
    """One provider row as raw JSON tokens (strings), so number text reaches the parser exactly as written."""
    return (str(ts), o, h, l, c, v, adj)


def body(rows, currency='"INR"', gmtoffset="19800", with_timestamp=True, with_adjclose=True, error="null"):
    cols = list(zip(*rows)) if rows else [[]] * 7
    join = lambda tokens: "[" + ",".join(tokens) + "]"  # noqa: E731
    meta = []
    if currency is not None:
        meta.append('"currency":%s' % currency)
    if gmtoffset is not None:
        meta.append('"gmtoffset":%s' % gmtoffset)
    result = ['"meta":{%s}' % ",".join(meta)]
    if with_timestamp:
        result.append('"timestamp":%s' % join(cols[0]))
    quote = '{"open":%s,"high":%s,"low":%s,"close":%s,"volume":%s}' % tuple(join(cols[i]) for i in range(1, 6))
    ind = ['"quote":[%s]' % quote]
    if with_adjclose:
        ind.append('"adjclose":[{"adjclose":%s}]' % join(cols[6]))
    result.append('"indicators":{%s}' % ",".join(ind))
    return '{"chart":{"result":[{%s}],"error":%s}}' % (",".join(result), error)


def ok(text):
    return lambda request: httpx.Response(200, content=text)


def provider(handler, **kw):
    return YahooProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def fetch(text, instrument=NSE, start=START, end=END):
    return provider(ok(text)).get_daily_bars(instrument, start, end, NOW)


DAY1, DAY2, DAY3 = epoch(2026, 3, 2), epoch(2026, 3, 3), epoch(2026, 3, 4)


def invalid(text, **kw):
    out = fetch(text, **kw)
    assert isinstance(out, BarFailure) and out.kind is BarFailureKind.INVALID_RESPONSE, out
    return out


# ---- request contract --------------------------------------------------------------------------------------------


def test_request_url_has_exactly_the_planned_parameters_and_no_events():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=body([row(DAY1)]))

    out = provider(handler).get_daily_bars(NSE, START, END, NOW)
    assert isinstance(out, RawBarBatch)
    (request,) = seen
    assert request.url.path == "/v8/finance/chart/ZZTEST.NS"
    assert dict(request.url.params) == {
        "interval": "1d",
        "period1": str(int((datetime(2026, 3, 1, tzinfo=UTC) - IST).timestamp())),  # 2026-03-01 00:00 IST
        "period2": str(int((datetime(2026, 3, 4, tzinfo=UTC) - IST).timestamp())),  # 2026-03-04 00:00 IST (end + 1 day)
        "includeAdjustedClose": "true",
    }
    assert "events" not in str(request.url) and "div" not in request.url.query.decode()
    assert request.method == "GET"


def test_bse_listing_maps_to_the_bo_suffix():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, content=body([row(DAY1)]))

    provider(handler).get_daily_bars(BSE, START, END, NOW)
    assert seen == ["/v8/finance/chart/ZZTEST.BO"]


def test_unmappable_symbol_is_not_found_without_a_request():
    def handler(request):
        raise AssertionError("must not call the provider")

    bad = Instrument("A B", Exchange.NSE)
    out = provider(handler).get_daily_bars(bad, START, END, NOW)
    assert isinstance(out, BarFailure) and out.kind is BarFailureKind.NOT_FOUND


def test_the_adapter_satisfies_the_historical_bar_protocol():
    assert isinstance(YahooProvider(), HistoricalBarProvider)


# ---- programming errors ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(retrieved_at=datetime(2026, 3, 10, 10, 0)),
        dict(start=date(2026, 3, 4), end=date(2026, 3, 3)),
        dict(start=date(2010, 1, 1), end=date(2026, 3, 3)),               # span beyond 3,660 days
        dict(start=datetime(2026, 3, 1), end=END),
        dict(start=START, end="2026-03-03"),
    ],
)
def test_bad_arguments_are_programming_errors_and_make_no_request(kwargs):
    def handler(request):
        raise AssertionError("must not call the provider")

    args = dict(instrument=NSE, start=START, end=END, retrieved_at=NOW)
    args.update(kwargs)
    with pytest.raises(ValueError):
        provider(handler).get_daily_bars(**args)


def test_the_longest_allowed_span_is_accepted():
    start = END - timedelta(days=3660)
    assert isinstance(fetch(body([row(DAY1)]), start=start), RawBarBatch)


# ---- success shape and provider-verbatim values (F1) -------------------------------------------------------------


def test_batch_is_provider_neutral_and_carries_the_offset_not_the_gmtoffset():
    out = fetch(body([row(DAY1), row(DAY2)]))
    assert isinstance(out, RawBarBatch)
    assert out.instrument == NSE and out.currency is Currency.INR and out.source == "yahoo"
    assert out.retrieved_at == NOW and out.exchange_utc_offset == IST
    assert (out.rows_returned, out.empty_rows_excluded, len(out.bars)) == (2, 0, 2)
    assert [f.name for f in dataclasses.fields(out)] == [
        "instrument", "bars", "currency", "source", "retrieved_at", "exchange_utc_offset",
        "rows_returned", "empty_rows_excluded",
    ]
    assert all(isinstance(b, RawBar) for b in out.bars)


def test_numbers_are_the_exact_decimals_of_the_json_text():
    tokens = dict(o="920.7383422851562", h="1477.4749755859375", l="894.755859375", c="1e3", adj="100", v="123")
    out = fetch(body([row(DAY1, **tokens)]))
    bar = out.bars[0]
    assert bar.open.as_tuple() == D("920.7383422851562").as_tuple()
    assert bar.high.as_tuple() == D("1477.4749755859375").as_tuple()
    assert bar.low.as_tuple() == D("894.755859375").as_tuple()
    assert bar.close.as_tuple() == D("1e3").as_tuple()           # exponent token kept as written, no rounding
    assert bar.adjusted_close.as_tuple() == D("100").as_tuple()  # integer token
    for value in (bar.open, bar.high, bar.low, bar.close, bar.adjusted_close):
        assert type(value) is D
    assert bar.volume == 123 and type(bar.volume) is int


def test_trailing_zeros_in_the_provider_text_are_not_normalised():
    bar = fetch(body([row(DAY1, c="105.50")])).bars[0]
    assert bar.close.as_tuple() == D("105.50").as_tuple()


def test_integral_volume_written_as_a_decimal_is_accepted():
    assert fetch(body([row(DAY1, v="2500.0")])).bars[0].volume == 2500


# ---- timestamps (F3) ---------------------------------------------------------------------------------------------


def test_any_provider_timestamp_is_preserved_and_session_date_uses_the_offset():
    stamps = [epoch(2026, 3, 2, 3, 45), epoch(2026, 3, 3, 3, 30), epoch(2026, 3, 4, 12, 45), epoch(2026, 3, 5, 9, 44)]
    out = fetch(body([row(s) for s in stamps]), end=date(2026, 3, 5))
    assert [b.timestamp for b in out.bars] == [datetime.fromtimestamp(s, tz=UTC) for s in stamps]
    assert all(b.timestamp.utcoffset() == timedelta(0) for b in out.bars)
    assert [b.session_date for b in out.bars] == [date(2026, 3, d) for d in (2, 3, 4, 5)]


def test_a_late_utc_timestamp_belongs_to_the_next_local_session_date():
    out = fetch(body([row(epoch(2026, 3, 2, 18, 29)), row(epoch(2026, 3, 3, 18, 30))]))
    assert [b.session_date for b in out.bars] == [date(2026, 3, 2), date(2026, 3, 4)]


# ---- empty rows (F4), zero volume (F5), short coverage (F2) ------------------------------------------------------


def test_all_null_rows_are_excluded_and_counted_never_filled():
    empty = row(DAY2, o="null", h="null", l="null", c="null", v="null", adj="null")
    out = fetch(body([row(DAY1), empty, row(DAY3)]))
    assert isinstance(out, RawBarBatch)
    assert (out.rows_returned, out.empty_rows_excluded) == (3, 1)
    assert [b.session_date for b in out.bars] == [date(2026, 3, 2), date(2026, 3, 4)]


@pytest.mark.parametrize("field", ["o", "h", "l", "c", "v", "adj"])
def test_a_partially_null_row_is_invalid_not_repaired(field):
    invalid(body([row(DAY1, **{field: "null"})]))


def test_zero_volume_is_valid():
    assert fetch(body([row(DAY1, v="0")])).bars[0].volume == 0


@pytest.mark.parametrize("volume", ["-1", "1.5", "true", '"5"', "1e30", "1e999999999", "[]"])
def test_invalid_volume_is_rejected(volume):
    invalid(body([row(DAY1, v=volume)]))


def test_short_coverage_is_a_valid_partial_batch():
    late = epoch(2026, 3, 3)
    out = fetch(body([row(late)]), start=date(2025, 1, 1), end=END)
    assert isinstance(out, RawBarBatch) and len(out.bars) == 1  # a single bar, far after the requested start
    many = fetch(body([row(DAY2), row(DAY3)]), start=date(2024, 1, 1), end=END)
    assert isinstance(many, RawBarBatch) and many.bars[0].session_date == date(2026, 3, 3)


def test_zero_rows_is_an_empty_batch_not_not_found():
    for text in (body([], with_timestamp=False, with_adjclose=False), body([])):
        out = fetch(text)
        assert isinstance(out, RawBarBatch) and out.bars == () and (out.rows_returned, out.empty_rows_excluded) == (0, 0)
    only_empty = row(DAY1, o="null", h="null", l="null", c="null", v="null", adj="null")
    out = fetch(body([only_empty, row(DAY2, o="null", h="null", l="null", c="null", v="null", adj="null")]))
    assert isinstance(out, RawBarBatch) and out.bars == () and (out.rows_returned, out.empty_rows_excluded) == (2, 2)


# ---- provider / network failures ---------------------------------------------------------------------------------


def test_404_is_not_found():
    out = provider(lambda r: httpx.Response(404, content="gone")).get_daily_bars(NSE, START, END, NOW)
    assert isinstance(out, BarFailure) and out.kind is BarFailureKind.NOT_FOUND


def test_a_not_found_error_object_is_not_found():
    text = '{"chart":{"result":null,"error":{"code":"Not Found","description":"x"}}}'
    out = fetch(text)
    assert isinstance(out, BarFailure) and out.kind is BarFailureKind.NOT_FOUND


@pytest.mark.parametrize("status", [429, 500, 502, 503, 403])
def test_http_errors_are_provider_errors(status):
    out = provider(lambda r: httpx.Response(status, content="x")).get_daily_bars(NSE, START, END, NOW)
    assert isinstance(out, BarFailure) and out.kind is BarFailureKind.PROVIDER_ERROR and str(status) in out.detail


def test_timeout_and_network_failures_are_provider_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx.ConnectError("down", request=request)

    assert provider(timeout).get_daily_bars(NSE, START, END, NOW).detail == "timeout"
    out = provider(down).get_daily_bars(NSE, START, END, NOW)
    assert out.kind is BarFailureKind.PROVIDER_ERROR


# ---- malformed / unacceptable responses --------------------------------------------------------------------------

GOOD = [row(DAY1)]


@pytest.mark.parametrize(
    "text",
    [
        "not json", "[]", "null", '{"unexpected":1}', '{"chart":null}', '{"chart":{"result":[]}}',
        '{"chart":{"result":null,"error":{"code":"Other"}}}', '{"chart":{"result":[{}]}}',
        '{"chart":{"result":[{"meta":{"currency":"INR","gmtoffset":19800},"timestamp":"x","indicators":{}}]}}',
        pytest.param("[" * 100000, id="deep-nesting"),
    ],
    ids=lambda t: None if len(t) > 80 else t,
)
def test_wrong_shape_is_invalid(text):
    invalid(text)


def test_currency_must_be_inr():
    invalid(body(GOOD, currency='"USD"'))
    invalid(body(GOOD, currency=None))


@pytest.mark.parametrize("offset", ["0", "19801", "null", "true", '"19800"', None])
def test_gmtoffset_must_be_exactly_19800(offset):
    invalid(body(GOOD, gmtoffset=offset))


def test_array_length_mismatch_is_invalid():
    text = body([row(DAY1), row(DAY2)]).replace('"close":[105,105]', '"close":[105]')
    assert text != body([row(DAY1), row(DAY2)])
    invalid(text)


def test_missing_adjusted_close_series_is_invalid():
    invalid(body(GOOD, with_adjclose=False))


def test_non_increasing_or_duplicate_session_dates_are_invalid():
    invalid(body([row(DAY2), row(DAY1)]))                                     # decreasing
    invalid(body([row(DAY1), row(DAY1)]))                                     # same timestamp
    invalid(body([row(epoch(2026, 3, 2, 3, 45)), row(epoch(2026, 3, 2, 9, 44))]))  # same IST session date


@pytest.mark.parametrize("stamp", ["null", '"x"', "1.5", "true", "99999999999999999", "-99999999999999999"])
def test_bad_timestamps_are_invalid(stamp):
    invalid(body([row(stamp)]))


@pytest.mark.parametrize(
    "price",
    ["0", "-1", "NaN", "Infinity", "-Infinity", '"100"', "true", "[]", "1e15", "1e30", "1e-21", "1e14"],
)
@pytest.mark.parametrize("column", ["o", "h", "l", "c", "adj"])
def test_prices_outside_the_numeric_guards_are_invalid(column, price):
    invalid(body([row(DAY1, **{column: price})]))


def test_price_exponent_boundaries_are_accepted():
    bar = fetch(body([row(DAY1, o="1e-20", l="1e-20", c="1e-20", adj="1e13", h="1e13")])).bars[0]
    assert bar.open == D("1e-20") and bar.adjusted_close == D("1e13")


def test_more_than_the_bar_cap_is_invalid():
    start = int(datetime(2000, 1, 3, 3, 45, tzinfo=UTC).timestamp())
    rows = [row(start + i * 86400) for i in range(6001)]
    invalid(body(rows), start=date(2020, 1, 1), end=date(2026, 3, 3))  # the response, not the request, exceeds the cap
    assert len(fetch(body(rows[:6000]), start=date(2020, 1, 1), end=date(2026, 3, 3)).bars) == 6000
