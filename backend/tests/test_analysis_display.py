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
    ("1234567.891", "₹12,34,567.89"), ("0.00004", "<₹0.0001"), ("0", "₹0.00"), ("-0.0475", "-₹0.0475"), ("0.12", "₹0.12"),
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
    assert dd.number("0.003728", "ratio") == {"value": "0.003728", "display": "0.37%", "unavailable_reason": None}
    assert dd.number("1234.5", "inr") == {"value": "1234.5", "display": "₹1,234.50", "unavailable_reason": None}
    assert dd.number("1234.5", "inr_lower_bound")["display"] == "₹1,234.50 (lower bound)"
    assert dd.number("0.01", "ratio_fees_excluded")["display"] == "1.00% (fees excluded)"
    assert dd.number("7", "count") == {"value": "7", "display": "7", "unavailable_reason": None}
    assert dd.number(None, "inr", "no series") == {"value": None, "display": "Unavailable", "unavailable_reason": "no series"}
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
