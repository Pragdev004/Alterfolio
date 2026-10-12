import json
from datetime import datetime, timezone
from decimal import Decimal as D

import httpx
import pytest

from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.providers.market.port import MarketQuote, QuoteFailure, QuoteFailureKind
from app.providers.market.yahoo import YahooProvider, yahoo_symbol

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
NSE = Instrument("ZZTEST", Exchange.NSE)
BSE = Instrument("ZZTEST", Exchange.BSE)
EPOCH = 1767600000  # 2026-01-05T08:00:00Z


def chart(price="2450.35", currency="INR", stamp=EPOCH):
    """Raw JSON text, so the price is a JSON number exactly as the provider would write it."""
    parts = []
    if currency is not None:
        parts.append('"currency":%s' % json.dumps(currency))
    if price is not None:
        parts.append('"regularMarketPrice":%s' % price)
    if stamp is not None:
        parts.append('"regularMarketTime":%s' % stamp)
    return '{"chart":{"result":[{"meta":{%s,"extra":"x"}}],"error":null}}' % ",".join(parts)


def provider(handler, **kw):
    return YahooProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def ok(body):
    return lambda request: httpx.Response(200, content=body)


def test_mapping_suffixes_and_canonicalization():
    assert yahoo_symbol(NSE) == "ZZTEST.NS" and yahoo_symbol(BSE) == "ZZTEST.BO"
    assert yahoo_symbol(Instrument(" zz-test ", Exchange.NSE)) == "ZZ-TEST.NS"
    assert yahoo_symbol(Instrument("ZZ TEST", Exchange.NSE)) is None
    assert yahoo_symbol(Instrument("A/../B", Exchange.NSE)) is None


def test_valid_quote_is_exact_decimal_utc_and_isolated_from_the_response():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, content=chart())

    q = provider(handler).get_quotes([NSE], NOW)[NSE]
    assert isinstance(q, MarketQuote)
    assert q.price == D("2450.35") and isinstance(q.price, D)
    assert q.currency is Currency.INR and q.source == "yahoo" and q.instrument == NSE
    assert q.price_timestamp == datetime.fromtimestamp(EPOCH, tz=timezone.utc) and q.retrieved_at == NOW
    assert seen == ["/v8/finance/chart/ZZTEST.NS"]
    assert set(vars(q)) == {"instrument", "price", "currency", "price_timestamp", "retrieved_at", "source"}


def test_integer_price_is_accepted():
    q = provider(ok(chart(price="100"))).get_quotes([NSE], NOW)[NSE]
    assert q.price == D(100)


@pytest.mark.parametrize(
    "body",
    [
        chart(currency="USD"),
        chart(currency=None),
        chart(price="0"),
        chart(price="-1.5"),
        chart(price='"10"'),
        chart(price="1e30"),
        chart(price=None),
        chart(stamp=None),
        chart(stamp='"x"'),
        chart(stamp="99999999999999999"),
        '{"chart":{"result":[]}}',
        '{"chart":{"result":null,"error":{"code":"Other"}}}',
        '{"unexpected":1}',
        "not json",
        "[]",
    ],
)
def test_unusable_responses_are_invalid_never_prices(body):
    out = provider(ok(body)).get_quotes([NSE], NOW)[NSE]
    assert isinstance(out, QuoteFailure) and out.kind is QuoteFailureKind.INVALID_RESPONSE


def test_unknown_symbol_is_not_found():
    body = '{"chart":{"result":null,"error":{"code":"Not Found","description":"x"}}}'
    out = provider(lambda r: httpx.Response(404, content=body)).get_quotes([NSE], NOW)[NSE]
    assert out.kind is QuoteFailureKind.NOT_FOUND


@pytest.mark.parametrize("status", [429, 500, 503, 403])
def test_http_errors_are_provider_errors(status):
    out = provider(lambda r: httpx.Response(status, content="x")).get_quotes([NSE], NOW)[NSE]
    assert out.kind is QuoteFailureKind.PROVIDER_ERROR and str(status) in out.detail


def test_timeout_and_network_failure_are_provider_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def down(request):
        raise httpx.ConnectError("down", request=request)

    assert provider(timeout).get_quotes([NSE], NOW)[NSE].detail == "timeout"
    assert provider(down).get_quotes([NSE], NOW)[NSE].kind is QuoteFailureKind.PROVIDER_ERROR


def test_partial_batch_keeps_good_quotes_and_flags_the_rest():
    def handler(request):
        if request.url.path.endswith("ZZTEST.NS"):
            return httpx.Response(200, content=chart())
        return httpx.Response(500, content="x")

    out = provider(handler).get_quotes([NSE, BSE, NSE], NOW)
    assert set(out) == {NSE, BSE}
    assert isinstance(out[NSE], MarketQuote) and out[BSE].kind is QuoteFailureKind.PROVIDER_ERROR


def test_unmappable_symbol_is_not_found_without_a_request():
    def handler(request):
        raise AssertionError("must not call the provider")

    bad = Instrument("A B", Exchange.NSE)
    assert provider(handler).get_quotes([bad], NOW)[bad].kind is QuoteFailureKind.NOT_FOUND


def test_time_budget_exhaustion_reports_timeout_for_the_rest():
    ticks = iter([0, 0, 100, 100, 100])
    p = provider(ok(chart()), total_budget_seconds=20, monotonic=lambda: next(ticks))
    out = p.get_quotes([NSE, BSE], NOW)
    assert isinstance(out[NSE], MarketQuote)
    assert out[BSE].kind is QuoteFailureKind.PROVIDER_ERROR and "budget" in out[BSE].detail


def test_naive_retrieved_at_is_a_programming_error():
    with pytest.raises(ValueError):
        provider(ok(chart())).get_quotes([NSE], datetime(2026, 1, 5))


def test_constructing_the_provider_does_not_touch_the_network():
    assert YahooProvider()._client is None
