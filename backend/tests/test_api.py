import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.api.main as api_main
from app.api.deps import get_current_user_id
from app.api.main import create_app
from app.config import Settings
from tests.conftest import USER_A, USER_B

ISIN = "ZZ0RELIANCE1"
BUY = {
    "symbol": "RELIANCE", "isin": ISIN, "name": "Reliance Industries", "asset_type": "STOCK", "exchange": "NSE",
    "side": "BUY", "quantity": "10", "price_per_unit": "100",
    "trade_timestamp": "2026-01-01T10:00:00Z", "market_session": "REGULAR",
}


def body(**kw):
    out = dict(BUY)
    out.update(kw)
    return out


@pytest.fixture
def app(engine, session, clock, id_factory):
    application = create_app(
        session_factory=sessionmaker(engine, expire_on_commit=False),
        settings=Settings(user_id=USER_A),
        clock=clock,
        id_factory=id_factory,
    )
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def as_user(app, user_id):
    app.dependency_overrides[get_current_user_id] = lambda: user_id


def test_health_needs_no_database():
    def boom():
        raise AssertionError("health must not open a session")

    r = TestClient(create_app(session_factory=boom, settings=Settings())).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_there_is_no_module_level_app_and_a_database_is_required_to_serve():
    assert not hasattr(api_main, "app")
    with pytest.raises(RuntimeError):
        create_app(settings=Settings(database_url=None))


def test_the_server_refuses_non_postgres_urls():
    # SQLite is test-only: NUMERIC affinity there would silently turn exact decimals into floats.
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app(settings=Settings(database_url="sqlite:///alterfolio.db"))


def test_create_trade_returns_server_fields_and_string_decimals(client):
    r = client.post("/trades", json=body())
    assert r.status_code == 201
    t = r.json()
    assert t["source"] == "MANUAL" and t["status"] == "EXECUTED" and t["currency"] == "INR"
    assert t["supersedes_trade_id"] is None and t["recorded_at"]
    assert t["quantity"] == "10.000000" and t["price_per_unit"] == "100.000000"
    assert t["brokerage_fee"] == "0.000000"
    assert "user_id" not in t


def test_fractional_decimals_round_trip_exactly(client):
    r = client.post("/trades", json=body(quantity="0.000001", price_per_unit="12345678901234.123456"))
    t = client.get(f"/trades/{r.json()['id']}").json()
    assert (t["quantity"], t["price_per_unit"]) == ("0.000001", "12345678901234.123456")


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": 10}, {"price_per_unit": 100.5},
        {"quantity": "abc"}, {"side": "HOLD"}, {"asset_type": "MUTUAL_FUND"},
        {"exchange": "NFO"}, {"currency": "USD"}, {"source": "IMPORT"},
        {"user_id": "00000000-0000-0000-0000-00000000000b"},
        {"market_session": None}, {"symbol": None},
    ],
)
def test_malformed_bodies_are_422(client, bad):
    assert client.post("/trades", json=body(**bad)).status_code == 422


def test_missing_required_field_is_422(client):
    payload = body()
    del payload["market_session"]
    assert client.post("/trades", json=payload).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": "0"}, {"price_per_unit": "-1"}, {"brokerage_fee": "-0.1"},
        {"quantity": "1.1234567"}, {"quantity": "NaN"},
        {"trade_timestamp": "2026-01-01T10:00:00"}, {"symbol": "  "},
    ],
)
def test_business_validation_uses_the_error_envelope(client, bad):
    r = client.post("/trades", json=body(**bad))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_trade"
    assert client.get("/trades").json() == []


def test_oversell_is_422_and_changes_nothing(client):
    client.post("/trades", json=body(quantity="5"))
    r = client.post("/trades", json=body(side="SELL", quantity="6", trade_timestamp="2026-01-01T11:00:00Z"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "oversell"
    assert len(client.get("/trades").json()) == 1


def test_get_trade_errors(client, app):
    t = client.post("/trades", json=body()).json()
    assert client.get("/trades/not-a-uuid").status_code == 422
    missing = client.get("/trades/00000000-0000-0000-0000-0000000000ff")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "trade_not_found"
    as_user(app, USER_B)
    assert client.get(f"/trades/{t['id']}").status_code == 404


def test_list_is_ordered_and_includes_history(client):
    late = client.post("/trades", json=body(trade_timestamp="2026-01-01T12:00:00Z")).json()
    early = client.post("/trades", json=body(trade_timestamp="2026-01-01T09:00:00Z")).json()
    client.post(f"/trades/{early['id']}/void")
    ids = [t["id"] for t in client.get("/trades").json()]
    assert ids[0] == early["id"] and late["id"] in ids and len(ids) == 3


def test_correct_creates_a_superseding_row(client):
    t = client.post("/trades", json=body()).json()
    r = client.post(f"/trades/{t['id']}/correct", json=body(quantity="8"))
    assert r.status_code == 201 and r.json()["supersedes_trade_id"] == t["id"]
    again = client.post(f"/trades/{t['id']}/correct", json=body(quantity="7"))
    assert again.status_code == 422 and again.json()["detail"]["code"] == "already_superseded"
    (h,) = client.get("/portfolio/holdings").json()
    assert h["quantity"] == "8.000000" and h["invested_amount"] == "800.000000"


def test_correction_causing_oversell_is_rejected(client):
    buy = client.post("/trades", json=body()).json()
    client.post("/trades", json=body(side="SELL", quantity="10", trade_timestamp="2026-01-01T11:00:00Z"))
    r = client.post(f"/trades/{buy['id']}/correct", json=body(quantity="5"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "oversell"


def test_void_creates_a_cancelled_row_and_clears_holdings(client):
    t = client.post("/trades", json=body()).json()
    r = client.post(f"/trades/{t['id']}/void")
    assert r.status_code == 201 and r.json()["status"] == "CANCELLED"
    assert client.get("/portfolio/holdings").json() == []
    assert client.post(f"/trades/{t['id']}/void").status_code == 422


def test_correct_and_void_of_unknown_trade_are_404(client):
    unknown = "00000000-0000-0000-0000-0000000000ff"
    assert client.post(f"/trades/{unknown}/correct", json=body()).status_code == 404
    assert client.post(f"/trades/{unknown}/void").status_code == 404


def test_holdings_values_as_of_and_empty(client):
    assert client.get("/portfolio/holdings").json() == []
    client.post("/trades", json=body())
    client.post("/trades", json=body(price_per_unit="200", trade_timestamp="2026-01-02T10:00:00Z"))
    (h,) = client.get("/portfolio/holdings").json()
    assert h == {
        "isin": ISIN, "listings": [{"symbol": "RELIANCE", "exchange": "NSE"}], "name": "Reliance Industries",
        "quantity": "20.000000", "average_buy_price": "150.000000", "invested_amount": "3000.000000",
        "cost_basis_complete": True,
        "quantity_display": "20", "average_buy_price_display": "₹150.00", "invested_amount_display": "₹3,000.00",
    }
    (past,) = client.get("/portfolio/holdings", params={"as_of": "2026-01-01T10:00:00Z"}).json()
    assert past["quantity"] == "10.000000" and past["average_buy_price"] == "100.000000"


def test_holdings_as_of_must_be_aware(client):
    r = client.get("/portfolio/holdings", params={"as_of": "2026-01-01T10:00:00"})
    assert r.status_code == 422
    assert client.get("/portfolio/holdings", params={"as_of": "garbage"}).status_code == 422


def test_inexact_average_is_quantized_once_at_the_boundary(client):
    client.post("/trades", json=body(quantity="1", price_per_unit="100"))
    client.post("/trades", json=body(quantity="2", price_per_unit="100.5", trade_timestamp="2026-01-01T11:00:00Z"))
    (h,) = client.get("/portfolio/holdings").json()
    assert h["average_buy_price"] == "100.333333" and h["invested_amount"] == "301.000000"


def test_routes_are_isolated_between_users(client, app):
    t = client.post("/trades", json=body()).json()
    as_user(app, USER_B)
    assert client.get("/trades").json() == []
    assert client.get("/portfolio/holdings").json() == []
    assert client.post(f"/trades/{t['id']}/correct", json=body()).status_code == 404
    assert client.post(f"/trades/{t['id']}/void").status_code == 404
    assert client.post("/trades", json=body(side="SELL", quantity="1")).json()["detail"]["code"] == "oversell"
    as_user(app, USER_A)
    assert len(client.get("/trades").json()) == 1


def test_buy_fees_and_taxes_are_in_the_holding_cost_but_sell_fees_are_not(client):
    client.post("/trades", json=body(brokerage_fee="10", taxes="5"))
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["invested_amount"], h["average_buy_price"]) == ("1015.000000", "101.500000")
    client.post(
        "/trades",
        json=body(side="SELL", quantity="4", price_per_unit="150", brokerage_fee="40", taxes="10",
                  trade_timestamp="2026-01-01T11:00:00Z"),
    )
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["quantity"], h["average_buy_price"]) == ("6.000000", "101.500000")
    assert h["invested_amount"] == "609.000000"


# ---- defect 4: oversized text is a client error, not a database 500 ----

TEXT_LIMITS = {"symbol": 64, "name": 256, "broker": 64, "broker_trade_id": 128, "order_id": 128, "notes": 2000}


@pytest.mark.parametrize("field,limit", sorted(TEXT_LIMITS.items()))
def test_text_at_the_limit_is_created_and_over_the_limit_is_422(client, field, limit):
    ok = client.post("/trades", json=body(**{field: "x" * limit}))
    assert ok.status_code == 201 and ok.json()[field] == "x" * limit
    over = client.post("/trades", json=body(**{field: "x" * (limit + 1)}))
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "invalid_trade" and field in over.json()["detail"]["message"]
    assert len(client.get("/trades").json()) == 1


def test_correct_route_validates_text_lengths_too(client):
    t = client.post("/trades", json=body()).json()
    r = client.post(f"/trades/{t['id']}/correct", json=body(symbol="S" * 65))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert len(client.get("/trades").json()) == 1


# ---- defect 3: no accepted trade can break the holdings read ----

BIG = "99999999999999"


def test_max_quantity_at_max_price_is_422_and_holdings_stay_healthy(client):
    r = client.post("/trades", json=body(quantity=BIG, price_per_unit=BIG))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "numeric_limit_exceeded"
    assert client.get("/trades").json() == []
    h = client.get("/portfolio/holdings")
    assert h.status_code == 200 and h.json() == []


def test_values_just_inside_the_limit_are_stored_and_reported_exactly(client):
    r = client.post("/trades", json=body(quantity="2", price_per_unit="99999999999.123456"))
    assert r.status_code == 201
    (h,) = client.get("/portfolio/holdings").json()
    assert h["invested_amount"] == "199999999998.246912" and h["average_buy_price"] == "99999999999.123456"


def test_cumulative_overflow_is_422_and_earlier_holdings_still_read(client):
    first = client.post("/trades", json=body(quantity="6", price_per_unit=BIG))
    assert first.status_code == 201
    second = client.post("/trades", json=body(quantity="6", price_per_unit=BIG, trade_timestamp="2026-01-01T11:00:00Z"))
    assert second.status_code == 422 and second.json()["detail"]["code"] == "numeric_limit_exceeded"
    holdings = client.get("/portfolio/holdings")
    assert holdings.status_code == 200 and holdings.json()[0]["invested_amount"] == "599999999999994.000000"


def test_correction_over_the_limit_is_422(client):
    t = client.post("/trades", json=body()).json()
    r = client.post(f"/trades/{t['id']}/correct", json=body(quantity=BIG, price_per_unit=BIG))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "numeric_limit_exceeded"
    assert client.get("/portfolio/holdings").status_code == 200


# ---- defect 2: duplicate manual trades return a client error, not 500 ----

def test_duplicate_broker_trade_id_is_422_and_stores_nothing(client):
    first = client.post("/trades", json=body(broker="zerodha", broker_trade_id="T1"))
    assert first.status_code == 201
    dup = client.post("/trades", json=body(broker="zerodha", broker_trade_id="T1", trade_timestamp="2026-01-01T11:00:00Z"))
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "duplicate_trade"
    assert [t["id"] for t in client.get("/trades").json()] == [first.json()["id"]]
    (h,) = client.get("/portfolio/holdings").json()
    assert h["quantity"] == "10.000000"


def test_duplicate_check_does_not_leak_or_block_other_users_and_corrections(client, app):
    first = client.post("/trades", json=body(broker="zerodha", broker_trade_id="T1")).json()
    as_user(app, USER_B)
    assert client.post("/trades", json=body(broker="zerodha", broker_trade_id="T1")).status_code == 201
    as_user(app, USER_A)
    fixed = client.post(f"/trades/{first['id']}/correct", json=body(broker="zerodha", broker_trade_id="T1", quantity="4"))
    assert fixed.status_code == 201


# ---- review round 3 ----

def test_empty_string_broker_duplicate_is_422_not_500(client):
    first = client.post("/trades", json=body(broker="", broker_trade_id="T1"))
    again = client.post("/trades", json=body(broker="", broker_trade_id="T1", trade_timestamp="2026-01-01T11:00:00Z"))
    assert first.status_code == 201 and again.status_code == 422
    assert again.json()["detail"]["code"] == "duplicate_trade"
    assert len(client.get("/trades").json()) == 1
    assert client.post("/trades", json=body(broker=None, broker_trade_id="T1")).status_code == 201


@pytest.mark.parametrize("field", ["quantity", "price_per_unit", "brokerage_fee", "taxes"])
@pytest.mark.parametrize("bad", ["0E+1000000", "0E+14", "0E-21", "1.000000000000000000000", "5." + "0" * 20000])
def test_extreme_decimal_exponents_are_422_and_store_nothing(client, field, bad):
    r = client.post("/trades", json=body(**{field: bad}))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert field in r.json()["detail"]["message"]
    assert client.get("/trades").json() == []


def test_zero_fee_in_range_is_still_accepted_and_reported_normally(client):
    r = client.post("/trades", json=body(brokerage_fee="0E-20", taxes="0.0000000"))
    assert r.status_code == 201 and r.json()["brokerage_fee"] == "0.000000"


@pytest.mark.parametrize("field", sorted(TEXT_LIMITS))
def test_nul_characters_are_422_for_every_bounded_text_field(client, field):
    r = client.post("/trades", json=body(**{field: "a\u0000b"}))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert field in r.json()["detail"]["message"]
    assert client.get("/trades").json() == []


def test_correct_route_rejects_nul_and_extreme_exponents_too(client):
    t = client.post("/trades", json=body()).json()
    assert client.post(f"/trades/{t['id']}/correct", json=body(notes="a\u0000b")).status_code == 422
    assert client.post(f"/trades/{t['id']}/correct", json=body(taxes="0E+1000000")).status_code == 422
    assert len(client.get("/trades").json()) == 1


# ---- final review M1 ----

@pytest.mark.parametrize("ts", ["0001-01-01T00:00:00+05:30", "9999-12-31T23:59:59-05:00"])
def test_timestamps_whose_utc_instant_overflows_are_422_not_500(client, ts):
    r = client.post("/trades", json=body(trade_timestamp=ts))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert "trade_timestamp" in r.json()["detail"]["message"]
    t = client.post("/trades", json=body()).json()
    assert client.post(f"/trades/{t['id']}/correct", json=body(trade_timestamp=ts)).status_code == 422
    assert len(client.get("/trades").json()) == 1


def test_window_boundary_timestamps_round_trip(client):
    low = client.post("/trades", json=body(trade_timestamp="0001-01-02T00:00:00Z", symbol="LOW", isin="ZZ0LOW000000"))
    high = client.post("/trades", json=body(trade_timestamp="9999-12-30T23:59:59.999999Z", symbol="HIGH", isin="ZZ0HIGH00000"))
    assert low.status_code == 201 and high.status_code == 201
    assert client.get(f"/trades/{low.json()['id']}").json()["trade_timestamp"].startswith("0001-01-02T00:00:00")
    assert client.get(f"/trades/{high.json()['id']}").json()["trade_timestamp"].startswith("9999-12-30T23:59:59")
    assert len(client.get("/portfolio/holdings").json()) == 2
    assert client.get("/portfolio/holdings", params={"as_of": "0001-01-02T00:00:00Z"}).status_code == 200


@pytest.mark.parametrize(
    "ts",
    ["0001-01-01T23:59:59.999999Z", "0001-01-01T00:00:00Z", "9999-12-31T00:00:00Z", "9999-12-31T23:59:59Z"],
)
def test_timestamps_outside_the_supported_window_are_422(client, ts):
    r = client.post("/trades", json=body(trade_timestamp=ts))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_trade"
    assert "trade_timestamp" in r.json()["detail"]["message"]
    assert client.get("/trades").json() == []
