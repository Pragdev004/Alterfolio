"""GET /portfolio/summary (Feature 003): contract, valuation status, current-only, isolation, no network."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.config import Settings
from app.domain.enums import Currency, Exchange
from app.domain.instrument import Instrument
from app.providers.market.port import MarketQuote, QuoteFailure, QuoteFailureKind
from app.repositories.trade_repository import TradeRepository
from tests.conftest import USER_A, USER_B, trade_fields
from tests.test_api import BUY, ISIN, as_user, body

NOW = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
RELIANCE = Instrument("RELIANCE", Exchange.NSE)
TCS_ISIN = "ZZ0TCS000000"


class FakeMarket:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []

    def get_quotes(self, instruments, retrieved_at):
        self.calls.append(list(instruments))
        return {i: self.outcomes[i] for i in instruments if i in self.outcomes}


def q(inst, price, age=timedelta(hours=1)):
    return MarketQuote(inst, D(price), Currency.INR, NOW - age, NOW, "fake")


@pytest.fixture
def market():
    return FakeMarket()


@pytest.fixture
def app(engine, session, id_factory, market):
    return create_app(
        session_factory=sessionmaker(engine, expire_on_commit=False),
        settings=Settings(user_id=USER_A),
        clock=lambda: NOW,
        id_factory=id_factory,
        market_data=market,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def summary(client, **params):
    r = client.get("/portfolio/summary", params=params)
    return r


def test_empty_portfolio_is_complete_zeros_not_an_error(client, market):
    r = summary(client)
    assert r.status_code == 200 and r.json() == {
        "schema_version": 1, "basis": "CURRENT", "valuation_time": "2026-03-02T10:00:00Z",
        "valuation_status": "COMPLETE", "total_trades": 0, "holdings_count": 0, "valued_holdings_count": 0,
        "total_invested": "0.000000", "total_market_value": "0.000000", "total_unrealized_pnl": "0.000000",
        "cost_basis_complete": True, "holdings": [],
        "valuation_time_display": "2 Mar 2026, 15:30 IST", "total_invested_display": "₹0.00",
        "total_market_value_display": "₹0.00", "total_unrealized_pnl_display": "₹0.00",
        "valuation_text": "0 of 0 holdings valued",
    }
    assert market.calls == []


def test_valued_holding_contract_and_decimal_strings(client, market):
    client.post("/trades", json=body())
    market.outcomes[RELIANCE] = q(RELIANCE, "120.5")
    s = summary(client).json()
    assert s["valuation_status"] == "COMPLETE" and s["total_trades"] == 1
    assert (s["total_invested"], s["total_market_value"], s["total_unrealized_pnl"]) == (
        "1000.000000", "1205.000000", "205.000000")
    (h,) = s["holdings"]
    assert h == {
        "isin": ISIN, "listings": [{"symbol": "RELIANCE", "exchange": "NSE"}], "name": "Reliance Industries",
        "quantity": "10.000000", "average_buy_price": "100.000000", "invested_amount": "1000.000000",
        "cost_basis_complete": True, "quote_status": "VALUED",
        "quote": {"symbol": "RELIANCE", "exchange": "NSE", "price": "120.500000", "currency": "INR",
                  "price_timestamp": "2026-03-02T09:00:00Z", "retrieved_at": "2026-03-02T10:00:00Z", "source": "fake",
                  "price_display": "₹120.50", "price_timestamp_display": "2 Mar 2026, 14:30 IST",
                  "retrieved_at_display": "2 Mar 2026, 15:30 IST"},
        "market_value": "1205.000000", "unrealized_pnl": "205.000000",
        "quantity_display": "10", "average_buy_price_display": "₹100.00", "invested_amount_display": "₹1,000.00",
        "market_value_display": "₹1,205.00", "unrealized_pnl_display": "₹205.00",
    }
    assert s["holdings_count"] == s["valued_holdings_count"] == 1


def test_summary_holdings_match_the_holdings_route(client, market):
    client.post("/trades", json=body())
    client.post("/trades", json=body(isin=TCS_ISIN, symbol="TCS", name="Tata Consultancy"))
    market.outcomes = {RELIANCE: q(RELIANCE, "110")}
    holdings = client.get("/portfolio/holdings").json()
    rows = summary(client).json()["holdings"]
    strip = ("quote_status", "quote", "market_value", "unrealized_pnl", "market_value_display", "unrealized_pnl_display",
             "market_value_unavailable_reason", "unrealized_pnl_unavailable_reason")
    assert [{k: v for k, v in r.items() if k not in strip} for r in rows] == holdings


def test_provider_down_is_200_unavailable_never_zero(client, market):
    client.post("/trades", json=body())
    market.outcomes[RELIANCE] = QuoteFailure(QuoteFailureKind.PROVIDER_ERROR, "timeout")
    r = summary(client)
    s = r.json()
    assert r.status_code == 200 and s["valuation_status"] == "UNAVAILABLE"
    assert s["total_market_value"] is None and s["total_unrealized_pnl"] is None
    assert s["total_invested"] == "1000.000000" and s["valued_holdings_count"] == 0
    h = s["holdings"][0]
    assert (h["quote_status"], h["quote"], h["market_value"], h["unrealized_pnl"]) == ("PROVIDER_ERROR", None, None, None)


def test_mixed_valuation_is_partial_with_valued_only_totals(client, market):
    client.post("/trades", json=body())
    client.post("/trades", json=body(isin=TCS_ISIN, symbol="TCS", name="Tata Consultancy"))
    market.outcomes = {RELIANCE: q(RELIANCE, "110"), Instrument("TCS", Exchange.NSE): QuoteFailure(QuoteFailureKind.NOT_FOUND, "x")}
    s = summary(client).json()
    assert s["valuation_status"] == "PARTIAL" and (s["holdings_count"], s["valued_holdings_count"]) == (2, 1)
    assert s["total_invested"] == "2000.000000" and s["total_market_value"] == "1100.000000"
    assert {h["isin"]: h["quote_status"] for h in s["holdings"]} == {ISIN: "VALUED", TCS_ISIN: "NOT_FOUND"}


def test_stale_quote_is_not_valued(client, market):
    client.post("/trades", json=body())
    market.outcomes[RELIANCE] = q(RELIANCE, "110", age=timedelta(days=30))
    s = summary(client).json()
    assert s["valuation_status"] == "UNAVAILABLE" and s["holdings"][0]["quote_status"] == "STALE"


def test_nse_bse_listings_of_one_isin_quote_nse_then_bse(client, market):
    client.post("/trades", json=body())
    client.post("/trades", json=body(exchange="BSE", trade_timestamp="2026-01-02T10:00:00Z"))
    bse = Instrument("RELIANCE", Exchange.BSE)
    market.outcomes = {RELIANCE: QuoteFailure(QuoteFailureKind.PROVIDER_ERROR, "x"), bse: q(bse, "99")}
    (h,) = summary(client).json()["holdings"]
    assert h["quote_status"] == "VALUED" and h["quote"]["exchange"] == "BSE" and h["market_value"] == "1980.000000"
    assert market.calls == [[RELIANCE, bse]]


def test_null_isin_legacy_holding_is_valued_separately(client, session, market):
    TradeRepository(session).add(user_id=USER_A, id=uuid4(), **trade_fields(isin=None, symbol="OLDCO", quantity=D("5")))
    session.commit()
    old = Instrument("OLDCO", Exchange.NSE)
    market.outcomes = {old: q(old, "10")}
    (h,) = summary(client).json()["holdings"]
    assert h["isin"] is None and h["market_value"] == "50.000000" and h["quote"]["symbol"] == "OLDCO"


def test_total_trades_counts_effective_trades_only(client, market):
    t = client.post("/trades", json=body()).json()
    client.post(f"/trades/{t['id']}/correct", json={k: v for k, v in BUY.items() if k != "currency"} | {"quantity": "4"})
    client.post("/trades", json=body(trade_timestamp="2026-01-03T10:00:00Z"))
    s = summary(client).json()
    assert s["total_trades"] == 2 and s["holdings"][0]["quantity"] == "14.000000"


@pytest.mark.parametrize("value", ["2026-01-01T10:00:00Z", "2026-01-01T10:00:00", "garbage"])
def test_as_of_is_rejected_not_ignored(client, market, value):
    client.post("/trades", json=body())
    r = summary(client, as_of=value)
    assert r.status_code == 422
    if value != "garbage":
        assert r.json()["detail"]["code"] == "historical_valuation_unsupported"
    assert market.calls == []


def test_summary_is_isolated_between_users(client, app, market):
    client.post("/trades", json=body())
    market.outcomes[RELIANCE] = q(RELIANCE, "110")
    as_user(app, USER_B)
    other = summary(client).json()
    assert other["total_trades"] == 0 and other["holdings"] == [] and other["valuation_status"] == "COMPLETE"
    as_user(app, USER_A)
    assert summary(client).json()["total_trades"] == 1


def test_default_app_builds_without_network_and_without_touching_the_provider(engine, session):
    app = create_app(session_factory=sessionmaker(engine), settings=Settings(user_id=USER_A))
    assert app.state.market_data._client is None
    r = TestClient(app).get("/portfolio/summary")
    assert r.status_code == 200 and r.json()["valuation_status"] == "COMPLETE"  # empty: no provider call


def test_existing_holdings_route_is_unchanged_by_the_provider(client, market):
    client.post("/trades", json=body())
    assert client.get("/portfolio/holdings").json()[0]["quantity"] == "10.000000"
    assert market.calls == []
