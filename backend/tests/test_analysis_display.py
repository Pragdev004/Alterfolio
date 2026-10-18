"""Feature 013a: server-side display strings (spec section 4, tests T6 and T11). Offline."""

import typing
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.schemas.imports as imports_schemas
import app.schemas.summary as summary_schemas
import app.schemas.trade as trade_schemas
from app.api.main import create_app
from app.config import Settings
from app.domain import display as dd
from app.schemas.display import WithDisplay
from tests.conftest import USER_A
from tests.test_api import ISIN, body

NOW = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("amount,text", [
    ("0.0475", "₹0.0475"), ("0.5", "₹0.50"), ("0.04751", "₹0.0475"), ("0.99996", "₹1.00"), ("1", "₹1.00"), ("100", "₹100.00"),
    ("1234567.891", "₹12,34,567.89"), ("0.00004", "<₹0.0001"), ("0", "₹0.00"), ("-0.0475", "−₹0.0475"), ("0.12", "₹0.12"),
    ("0.1", "₹0.10"), ("19.5947877483809985", "₹19.59")])
def test_price_is_two_dp_and_up_to_four_below_one_rupee(amount, text):
    assert dd.format_price(amount) == text


def test_dates_are_ist_and_unpadded():
    assert dd.format_date(date(2026, 10, 16)) == "16 Oct 2026"
    assert dd.format_date(date(2026, 3, 2)) == "2 Mar 2026"
    assert dd.format_datetime_ist(datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)) == "16 Oct 2026, 10:30 IST"
    assert dd.format_datetime_ist(datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)) == "17 Oct 2026, 01:30 IST"
    with pytest.raises(ValueError):
        dd.format_datetime_ist(datetime(2026, 10, 16, 5, 0))  # naive timestamps are rejected


def test_plain_quantity_keeps_every_digit_without_exponent():
    assert dd.format_plain("10.000000") == "10"
    assert dd.format_plain("0.000001") == "0.000001"
    assert dd.format_plain("1E+3") == "1000"
    assert dd.format_plain("12.50") == "12.5"


def test_number_object_shape_and_unavailable():
    assert dd.number("0.003728", "ratio") == {"value": "0.003728", "display": "0.37%", "unavailable_reason": None, "reason_text": None}
    assert dd.number("1234.5", "inr") == {"value": "1234.5", "display": "₹1,234.50", "unavailable_reason": None, "reason_text": None}
    assert dd.number("1234.5", "inr_lower_bound")["display"] == "₹1,234.50 (lower bound)"
    assert dd.number("0.01", "ratio_fees_excluded")["display"] == "1.00% (fees excluded)"
    assert dd.number("7", "count") == {"value": "7", "display": "7", "unavailable_reason": None, "reason_text": None}
    n = dd.number(None, "inr", "NO_MEMBERSHIP: Nifty 50 membership is not configured")
    assert n["value"] is None and n["display"] == "Unavailable" and n["unavailable_reason"].startswith("NO_MEMBERSHIP")
    assert n["reason_text"] == "Nifty 50 membership is not set up, so this comparison cannot be made."
    for kind in ("inr", "ratio", "price", "count", "plain"):
        n = dd.number(None, kind)
        assert n["value"] is None and n["display"] == "Unavailable" and n["unavailable_reason"]  # a reason is always given
    assert dd.number("0", "ratio")["display"] == "0.00%"  # a genuine zero stays a number
    with pytest.raises(ValueError):
        dd.number("NaN", "ratio")
    with pytest.raises(ValueError):
        dd.number("1", "bogus")


def _decimal_or_datetime_fields(model) -> set[str]:
    out = set()
    for name, hint in typing.get_type_hints(model, include_extras=True).items():
        if name.startswith("_") or name not in model.model_fields:
            continue
        stack = [hint]
        while stack:
            h = stack.pop()
            if typing.get_origin(h) is typing.Annotated:
                stack.append(typing.get_args(h)[0])
            elif typing.get_origin(h) is not None:
                stack.extend(typing.get_args(h))
            elif h in (Decimal, datetime):
                out.add(name)
    return out


def test_t6_every_decimal_and_datetime_field_of_every_output_schema_has_a_display_sibling():
    from pydantic import BaseModel
    seen = 0
    for module in (trade_schemas, summary_schemas, imports_schemas):
        for name, cls in vars(module).items():
            if not (isinstance(cls, type) and issubclass(cls, BaseModel) and name.endswith("Out") and cls.__module__ == module.__name__):
                continue
            wanted = _decimal_or_datetime_fields(cls)
            if wanted:
                assert issubclass(cls, WithDisplay), f"{name} has Decimal/datetime fields but no display siblings"
                assert set(cls.display_fields()) == wanted, name
                seen += 1
    assert seen >= 5  # TradeOut, HoldingOut, QuoteOut, SummaryHoldingOut, SummaryOut


@pytest.fixture
def client(engine, session, id_factory):
    class Market:
        def get_quotes(self, instruments, retrieved_at):
            return {}

    app = create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=USER_A),
                     clock=lambda: NOW, id_factory=id_factory, market_data=Market())
    return TestClient(app)


def test_t6_trades_endpoint_adds_display_keys(client):
    t = client.post("/trades", json=body(quantity="10", price_per_unit="0.0475")).json()
    assert t["quantity"] == "10.000000" and t["price_per_unit"] == "0.047500"  # raw values unchanged
    assert t["quantity_display"] == "10" and t["price_per_unit_display"] == "₹0.0475"
    assert t["brokerage_fee_display"] == "₹0.00" and t["taxes_display"] == "₹0.00"
    assert t["trade_timestamp_display"] == "1 Jan 2026, 15:30 IST" and t["recorded_at_display"].endswith(" IST")
    assert client.get("/trades").json()[0]["price_per_unit_display"] == "₹0.0475"


def test_t6_unknown_fees_on_an_imported_row_are_unavailable_not_zero(client, session):
    from analysis_helpers import add_trade
    from app.domain.enums import TradeSide
    add_trade(session, USER_A, TradeSide.BUY, date(2026, 1, 5), charges_provided=False)
    session.commit()
    (t,) = client.get("/trades").json()
    assert t["brokerage_fee"] == "0.000000" and t["taxes"] == "0.000000"  # raw values unchanged
    assert t["brokerage_fee_display"] == "Unavailable" and t["taxes_display"] == "Unavailable"
    assert "not provided" in t["brokerage_fee_unavailable_reason"] and t["price_per_unit_display"].startswith("₹")


def test_t6_holdings_and_summary_add_display_keys(client):
    client.post("/trades", json=body())
    h = client.get("/portfolio/holdings").json()[0]
    assert h["average_buy_price"] == "100.000000" and h["average_buy_price_display"] == "₹100.00"
    assert h["invested_amount_display"] == "₹1,000.00" and h["quantity_display"] == "10"
    s = client.get("/portfolio/summary").json()
    assert s["total_invested_display"] == "₹1,000.00"
    assert s["total_market_value"] is None and s["total_market_value_display"] == "Unavailable"  # no quote: never 0
    assert s["total_market_value_unavailable_reason"] and s["total_unrealized_pnl_display"] == "Unavailable"
    assert s["valuation_text"] == "0 of 1 holdings valued" and s["valuation_time_display"] == "2 Mar 2026, 15:30 IST"
    (sh,) = s["holdings"]
    assert sh["market_value_display"] == "Unavailable" and sh["market_value_unavailable_reason"]
    assert sh["isin"] == ISIN and sh["invested_amount_display"] == "₹1,000.00"


def test_partial_valuation_is_noted_on_the_totals(engine, session, id_factory):
    from app.domain.enums import Currency, Exchange
    from app.domain.instrument import Instrument
    from app.providers.market.port import MarketQuote

    class Market:
        def get_quotes(self, instruments, retrieved_at):
            inst = Instrument("RELIANCE", Exchange.NSE)
            return {i: MarketQuote(i, Decimal("120.5"), Currency.INR, NOW, NOW, "fake") for i in instruments if i == inst}

    app = create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=USER_A),
                     clock=lambda: NOW, id_factory=id_factory, market_data=Market())
    c = TestClient(app)
    c.post("/trades", json=body())
    c.post("/trades", json=body(isin="ZZ0TCS000000", symbol="TCS", name="Tata Consultancy"))
    s = c.get("/portfolio/summary").json()
    assert s["valuation_status"] == "PARTIAL" and s["valuation_text"] == "1 of 2 holdings valued"
    assert s["total_market_value_display"] == "₹1,205.00 (partial: 1 of 2 holdings valued)"
    assert s["total_unrealized_pnl_display"].endswith("(partial: 1 of 2 holdings valued)")
    assert s["total_invested_display"] == "₹2,000.00"  # invested covers every holding: no note
    assert "partial" not in s["holdings"][0]["market_value_display"]


def test_openapi_documents_the_display_contract_and_every_analysis_schema(client):
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    paths = spec["paths"]
    for path, model in (("/api/analysis/meta", "MetaOut"), ("/api/analysis/trips", "TripsOut"),
                        ("/api/analysis/trips/{trip_id}", "TripDetailOut"), ("/api/analysis/regimes", "RegimesOut"),
                        ("/api/analysis/biases", "BiasesOut")):
        ref = paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith(f"/{model}") and model in schemas
    assert set(schemas["NumberOut"]["properties"]) == {"value", "display", "unavailable_reason", "reason_text"}
    assert set(schemas["NumberOut"]["required"]) == {"value", "display", "unavailable_reason", "reason_text"}
    assert {"iso", "display"} == set(schemas["DateOut"]["properties"])
    for name in ("TripRowOut", "BaselineSummaryOut", "BiasOut", "BlockOut", "ProfileOut", "SampleOut", "HistogramOut", "BinOut",
                 "PickExclusionOut"):
        assert name in schemas, name
    # server-added display siblings of the existing endpoints are listed too (serialization schemas)
    assert "price_per_unit_display" in schemas["TradeOut"]["properties"]
    assert "price_per_unit_unavailable_reason" in schemas["TradeOut"]["properties"]
    assert {"total_market_value_display", "valuation_text"} <= set(schemas["SummaryOut"]["properties"])
    assert "market_value_display" in schemas["SummaryHoldingOut"]["properties"]
    assert "invested_amount_display" in schemas["HoldingOut"]["properties"]
    assert "price_display" in schemas["QuoteOut"]["properties"]
    assert "price_per_unit_display" in schemas["TradeOut"]["required"]


@pytest.mark.parametrize("ratio,text", [("0.612", "61%"), ("0.615", "62%"), ("0.605", "60%"), ("0.005", "0%"), ("-0.004", "0%"), ("1", "100%"),
                                         ("0", "0%"), ("0.5384", "54%")])
def test_percentile_displays_with_no_decimals_half_even(ratio, text):
    assert dd.number(ratio, "percentile")["display"] == text
    assert dd.number(None, "percentile", "x")["display"] == "Unavailable"


@pytest.mark.parametrize("value,word", [("0.0128", "ahead"), ("-0.0003", "behind"), ("0", "level"), ("0.00", "level"), (None, None)])
def test_direction_is_explicit(value, word):
    assert dd.direction(value) == word


@pytest.mark.parametrize("reason,text", [
    ("INSUFFICIENT_TRIPS: 7 trips available, 10 needed", "Not enough closed trips for an interval yet: 7 trips · 10 needed."),
    ("INSUFFICIENT_TRIPS_IN_REGIME: 3 trips available, 10 needed", "Not enough trips in this regime yet: 3 trips · 10 needed."),
    ("NO_MEMBERSHIP: Nifty 50 membership is not configured", "Nifty 50 membership is not set up, so this comparison cannot be made."),
    ("CORPORATE_ACTION_COVERAGE_UNDECLARED", "Which listings have had splits, bonuses or dividends has not been reviewed, so luck is not computed."),
    ("no exit bar", "No price was available on the trip's closing date."),
    ("insufficient history", "Not enough price history."),
    ("not computed", "This was not computed."),
])
def test_reason_text_is_a_plain_sentence(reason, text):
    assert dd.reason_text(reason) == text


def test_reason_text_covers_every_code_the_quant_can_raise():
    import re
    from app.quant.luck_test.errors import ExclusionReason, UnavailableReason as LuckReason
    from app.quant.regime_split.errors import UnavailableReason as RegimeReason
    raw = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b")
    for code in [*(r.value for r in LuckReason), *(r.value for r in ExclusionReason), *(r.value for r in RegimeReason)]:
        for reason in (code, f"{code}: some detail"):
            text = dd.reason_text(reason)
            assert text and text.endswith(".") and not raw.search(text), (reason, text)
            assert text != dd.reason_text("SOMETHING_UNKNOWN_HERE")  # a real mapping, not the fallback
    unknown = dd.reason_text("SOMETHING_UNKNOWN_HERE")
    assert not raw.search(unknown) and unknown.endswith(".")


def test_existing_endpoints_give_plain_reasons(client):
    client.post("/trades", json=body())
    s = client.get("/portfolio/summary").json()
    assert s["total_market_value_unavailable_reason"] == "Only 0 of 1 holdings could be priced."
    assert s["holdings"][0]["market_value_unavailable_reason"] == "The price source did not answer."


@pytest.mark.parametrize("mean,lo,hi,word", [
    ("0.02", "-0.01", "0.05", "inconclusive"), ("0.02", "0", "0.05", "inconclusive"), ("-0.02", "-0.05", "0.01", "inconclusive"),
    ("0.02", "0.01", "0.05", "ahead"), ("-0.02", "-0.05", "-0.01", "behind"), ("0.02", None, None, "ahead"), (None, None, None, None)])
def test_interval_direction(mean, lo, hi, word):
    assert dd.interval_direction(mean, lo, hi) == word
    assert dd.direction_text(word) == ("not distinguishable from zero" if word == "inconclusive" else word)
