"""Manual trade API for Feature 002: ISIN required, correction rules (3a), void (H-4), ISIN-grouped holdings.

All on in-memory SQLite. Legacy NULL-ISIN rows are written straight to the repository (the API can no longer create them).
"""
from datetime import timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.enums import Exchange, TradeSource
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import HoldingOut, TradeCorrectionIn, TradeIn, TradeOut
from tests.conftest import T0, USER_A, USER_B, make_batch, trade_fields
from tests.test_api import BUY, ISIN, app, as_user, body, client  # noqa: F401  (fixtures)
from tests.test_api_imports import post_csv
from tests.test_tradebook_import import ALPHA, csv_bytes, r

OTHER = "ZZ0TCS000000"
CORRECTION = {k: v for k, v in BUY.items() if k != "currency"}


def correction(**kw):
    out = dict(CORRECTION)
    out.update(kw)
    return out


def legacy_row(session, user=USER_A, **kw):
    row = TradeRepository(session).add(user_id=user, id=uuid4(), **trade_fields(isin=None, **kw))
    session.commit()
    return row


def imported_trade(client, **kw):
    """Import one synthetic row through the route and return it as the API shows it."""
    post_csv(client, csv_bytes(r(1, **kw)))
    return next(t for t in client.get("/trades").json() if t["source"] == "IMPORT")


# ---- schemas -------------------------------------------------------------------------------------------------------

def test_trade_in_requires_an_isin():
    TradeIn(**BUY)
    with pytest.raises(ValidationError):
        TradeIn(**{k: v for k, v in BUY.items() if k != "isin"})


def test_correction_in_requires_an_isin_and_allows_omitted_descriptive_fields_and_fees():
    only_required = {k: BUY[k] for k in ("symbol", "isin", "exchange", "side", "quantity", "price_per_unit", "trade_timestamp")}
    c = TradeCorrectionIn(**only_required)
    assert (c.name, c.asset_type, c.market_session, c.brokerage_fee, c.taxes) == (None, None, None, None, None)
    with pytest.raises(ValidationError):
        TradeCorrectionIn(**{k: v for k, v in only_required.items() if k != "isin"})
    assert TradeCorrectionIn(**only_required, brokerage_fee="0").brokerage_fee == D(0)  # an explicit zero is a value
    with pytest.raises(ValidationError):
        TradeCorrectionIn(**only_required, surprise=1)  # extra fields are forbidden


def test_trade_out_accepts_the_imported_shape_and_keeps_decimals_as_strings():
    row = dict(
        id=uuid4(), symbol="A", isin=ALPHA, name=None, asset_type=None, exchange=Exchange.NSE, currency="INR", side="BUY",
        quantity=D("1.5"), price_per_unit=D("2"), brokerage_fee=D(0), taxes=D(0), trade_timestamp=T0, recorded_at=T0,
        broker=None, broker_trade_id=None, order_id=None, supersedes_trade_id=None, source="IMPORT", market_session=None,
        status="EXECUTED", notes=None, charges_provided=False, import_batch_id=uuid4(),
    )
    dumped = TradeOut(**row).model_dump(mode="json")
    assert dumped["quantity"] == "1.500000" and dumped["charges_provided"] is False and dumped["name"] is None


def test_holding_out_shape():
    assert list(HoldingOut.model_fields) == [
        "isin", "listings", "name", "quantity", "average_buy_price", "invested_amount", "cost_basis_complete",
    ]


# ---- create --------------------------------------------------------------------------------------------------------

def test_create_stores_the_isin_and_affirms_charges(client):
    t = client.post("/trades", json=body()).json()
    assert (t["isin"], t["charges_provided"], t["source"], t["import_batch_id"]) == (ISIN, True, "MANUAL", None)
    assert client.get(f"/trades/{t['id']}").json() == t


def test_create_without_an_isin_is_422(client):
    payload = {k: v for k, v in BUY.items() if k != "isin"}
    resp = client.post("/trades", json=payload)
    assert resp.status_code == 422
    assert client.get("/trades").json() == []


@pytest.mark.parametrize("bad", ["", "SHORT", ISIN.lower(), ISIN + "X", "ZZ0RELIANCÉ1", "ZZ0RELIANCE ", None, 123456789012])
def test_create_with_a_malformed_isin_is_422_and_stores_nothing(client, bad):
    resp = client.post("/trades", json=body(isin=bad))
    assert resp.status_code == 422
    if isinstance(bad, str):
        assert resp.json()["detail"]["code"] == "invalid_trade"
    assert client.get("/trades").json() == []


def test_manual_trades_still_require_name_asset_type_and_market_session(client):
    for field in ("name", "asset_type", "market_session"):
        assert client.post("/trades", json=body(**{field: None})).status_code == 422
        assert client.post("/trades", json={k: v for k, v in BUY.items() if k != field}).status_code == 422


def test_there_is_no_update_or_delete_api(client):
    t = client.post("/trades", json=body()).json()
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)(f"/trades/{t['id']}").status_code == 405


def test_legacy_null_isin_rows_still_list_and_stay_separate_holdings(client, session):
    legacy_row(session, symbol="RELIANCE", quantity=D("5"))
    client.post("/trades", json=body(quantity="3"))
    rows = client.get("/trades").json()
    assert sorted(t["isin"] or "" for t in rows) == ["", ISIN]
    holdings = client.get("/portfolio/holdings").json()
    assert [(h["isin"], h["quantity"]) for h in holdings] == [(ISIN, "3.000000"), (None, "5.000000")]
    assert holdings[1]["listings"] == [{"symbol": "RELIANCE", "exchange": "NSE"}]


# ---- correct (plan 002a 3a) --------------------------------------------------------------------------------------------

def test_a_correction_requires_an_isin(client):
    t = client.post("/trades", json=body()).json()
    payload = {k: v for k, v in CORRECTION.items() if k != "isin"}
    assert client.post(f"/trades/{t['id']}/correct", json=payload).status_code == 422
    assert len(client.get("/trades").json()) == 1


def test_a_correction_replaces_the_trade_and_can_change_the_isin(client):
    t = client.post("/trades", json=body()).json()
    resp = client.post(f"/trades/{t['id']}/correct", json=correction(isin=OTHER, quantity="4"))
    assert resp.status_code == 201
    fixed = resp.json()
    assert (fixed["isin"], fixed["quantity"], fixed["supersedes_trade_id"], fixed["charges_provided"]) == (OTHER, "4.000000", t["id"], True)
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["isin"], h["quantity"]) == (OTHER, "4.000000")


def test_a_correction_cannot_erase_a_known_value(client):
    t = client.post("/trades", json=body()).json()
    for field in ("name", "asset_type", "market_session"):
        omitted = client.post(f"/trades/{t['id']}/correct", json={k: v for k, v in CORRECTION.items() if k != field})
        assert omitted.status_code == 422 and omitted.json()["detail"]["code"] == "invalid_trade"
        assert "cannot be erased" in omitted.json()["detail"]["message"]
        nulled = client.post(f"/trades/{t['id']}/correct", json=correction(**{field: None}))
        assert nulled.status_code == 422
    assert len(client.get("/trades").json()) == 1


def test_a_correction_of_an_imported_trade_may_stay_null_but_must_state_the_fees(client):
    imported = imported_trade(client)
    base = correction(symbol="ALPHACO", isin=ALPHA, name=None, asset_type=None, market_session=None)
    base.pop("name"), base.pop("asset_type"), base.pop("market_session")
    url = f"/trades/{imported['id']}/correct"
    for given in ({}, {"brokerage_fee": "0"}, {"taxes": "0"}, {"brokerage_fee": None, "taxes": None}):
        bad = client.post(url, json={**base, **given})
        assert bad.status_code == 422, given
        assert "must both be stated" in bad.json()["detail"]["message"]
    ok = client.post(url, json={**base, "brokerage_fee": "0", "taxes": "0"})  # an explicit zero counts
    assert ok.status_code == 201, ok.text
    fixed = ok.json()
    assert (fixed["name"], fixed["asset_type"], fixed["market_session"]) == (None, None, None)
    assert (fixed["source"], fixed["import_batch_id"], fixed["charges_provided"], fixed["isin"]) == ("MANUAL", None, True, ALPHA)
    assert imported["charges_provided"] is False  # the original row is untouched


def test_a_correction_with_a_known_target_defaults_omitted_fees_to_zero(client):
    t = client.post("/trades", json=body(brokerage_fee="3", taxes="1")).json()
    fixed = client.post(f"/trades/{t['id']}/correct", json=correction()).json()
    assert (fixed["brokerage_fee"], fixed["taxes"]) == ("0.000000", "0.000000")


def test_a_correction_cannot_oversell_and_other_users_ids_are_404(client, app):
    buy = client.post("/trades", json=body(trade_timestamp="2026-01-01T10:00:00Z")).json()
    client.post("/trades", json=body(side="SELL", trade_timestamp="2026-01-02T10:00:00Z"))
    shrink = client.post(f"/trades/{buy['id']}/correct", json=correction(quantity="5"))
    assert shrink.status_code == 422 and shrink.json()["detail"]["code"] == "oversell"
    as_user(app, USER_B)
    assert client.post(f"/trades/{buy['id']}/correct", json=correction()).status_code == 404


def test_a_correction_cannot_leave_an_nse_buy_short_of_a_bse_sell_of_the_same_isin(client):
    buy = client.post("/trades", json=body(trade_timestamp="2026-01-01T10:00:00Z")).json()
    client.post("/trades", json=body(side="SELL", exchange="BSE", trade_timestamp="2026-01-02T10:00:00Z"))
    resp = client.post(f"/trades/{buy['id']}/correct", json=correction(quantity="9"))
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "oversell"


# ---- void (H-4) --------------------------------------------------------------------------------------------------------

def test_void_preserves_the_isin_and_charges_of_an_imported_trade(client):
    imported = imported_trade(client)
    resp = client.post(f"/trades/{imported['id']}/void")
    assert resp.status_code == 201
    void = resp.json()
    assert (void["status"], void["supersedes_trade_id"]) == ("CANCELLED", imported["id"])
    assert (void["isin"], void["charges_provided"]) == (ALPHA, False)
    assert (void["source"], void["import_batch_id"]) == ("MANUAL", None)
    assert (void["name"], void["asset_type"], void["market_session"]) == (None, None, None)
    assert client.get("/portfolio/holdings").json() == []


def test_void_of_a_manual_trade_keeps_its_isin(client):
    t = client.post("/trades", json=body()).json()
    void = client.post(f"/trades/{t['id']}/void").json()
    assert (void["isin"], void["charges_provided"], void["source"]) == (ISIN, True, "MANUAL")


def test_voiding_the_buy_that_covers_a_cross_exchange_sell_is_refused(client):
    buy = client.post("/trades", json=body(trade_timestamp="2026-01-01T10:00:00Z")).json()
    client.post("/trades", json=body(side="SELL", exchange="BSE", trade_timestamp="2026-01-02T10:00:00Z"))
    assert client.post(f"/trades/{buy['id']}/void").status_code == 422


# ---- holdings API ------------------------------------------------------------------------------------------------------

def test_holdings_group_one_isin_across_exchanges_with_sorted_listings(client):
    client.post("/trades", json=body(quantity="1", price_per_unit="10", trade_timestamp="2026-01-01T10:00:00Z"))
    client.post("/trades", json=body(exchange="BSE", quantity="2", price_per_unit="20", trade_timestamp="2026-01-02T10:00:00Z"))
    (h,) = client.get("/portfolio/holdings").json()
    assert h == {
        "isin": ISIN, "listings": [{"symbol": "RELIANCE", "exchange": "BSE"}, {"symbol": "RELIANCE", "exchange": "NSE"}],
        "name": "Reliance Industries", "quantity": "3.000000", "average_buy_price": "16.666667",
        "invested_amount": "50.000000", "cost_basis_complete": True,
        "quantity_display": "3", "average_buy_price_display": "₹16.67", "invested_amount_display": "₹50.00",
    }


def test_holdings_name_and_listings_follow_as_of(client):
    client.post("/trades", json=body(name="Old Name", trade_timestamp="2026-01-01T10:00:00Z"))
    client.post("/trades", json=body(name="New Name", exchange="BSE", trade_timestamp="2026-01-03T10:00:00Z"))
    (early,) = client.get("/portfolio/holdings", params={"as_of": "2026-01-02T00:00:00Z"}).json()
    assert (early["name"], early["listings"], early["quantity"]) == (
        "Old Name", [{"symbol": "RELIANCE", "exchange": "NSE"}], "10.000000",
    )
    (late,) = client.get("/portfolio/holdings").json()
    assert late["name"] == "New Name" and len(late["listings"]) == 2
    assert client.get("/portfolio/holdings", params={"as_of": "2025-01-01T00:00:00Z"}).json() == []


def test_holdings_are_ordered_by_isin_then_legacy_listing_and_exited_ones_are_omitted(client, session):
    client.post("/trades", json=body(symbol="TCS", isin=OTHER, trade_timestamp="2026-01-01T10:00:00Z"))
    client.post("/trades", json=body(trade_timestamp="2026-01-01T11:00:00Z"))
    client.post("/trades", json=body(symbol="GONE", isin="ZZ0GONE00000", trade_timestamp="2026-01-01T12:00:00Z"))
    client.post("/trades", json=body(symbol="GONE", isin="ZZ0GONE00000", side="SELL", trade_timestamp="2026-01-02T12:00:00Z"))
    legacy_row(session, symbol="AAA")
    assert [h["isin"] for h in client.get("/portfolio/holdings").json()] == [ISIN, OTHER, None]


def test_cost_basis_completeness_through_the_api(client):
    imported = imported_trade(client, qty="10")
    assert client.get("/portfolio/holdings").json()[0]["cost_basis_complete"] is False
    sell = body(isin=ALPHA, symbol="ALPHACO", side="SELL", quantity="10", trade_timestamp="2026-01-01T10:00:00Z")
    assert client.post("/trades", json=sell).status_code == 201  # a full exit ends the epoch
    assert client.get("/portfolio/holdings").json() == []
    client.post("/trades", json=body(isin=ALPHA, symbol="ALPHACO", trade_timestamp="2026-01-02T10:00:00Z"))
    assert client.get("/portfolio/holdings").json()[0]["cost_basis_complete"] is True
    assert imported["charges_provided"] is False


def test_missing_sell_charges_never_make_the_basis_incomplete(client):
    client.post("/trades", json=body(isin=ALPHA, symbol="ALPHACO", quantity="10", trade_timestamp="2026-01-01T10:00:00Z"))
    post_csv(client, csv_bytes(r(1, side="sell", qty="4", ts="2026-01-02T09:00:00")))
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["quantity"], h["cost_basis_complete"]) == ("6.000000", True)


def test_holdings_are_isolated_between_users(client, app):
    client.post("/trades", json=body())
    as_user(app, USER_B)
    assert client.get("/portfolio/holdings").json() == []
    client.post("/trades", json=body(quantity="2"))
    assert client.get("/portfolio/holdings").json()[0]["quantity"] == "2.000000"
    as_user(app, USER_A)
    assert client.get("/portfolio/holdings").json()[0]["quantity"] == "10.000000"


# ---- final checkpoint: known zero vs charges not provided, and historical listings ---------------------------------------

def _imported_correction_base(client):
    """An imported (charges_provided=false) trade and a correction body for it that states no fees."""
    imported = imported_trade(client)
    base = correction(symbol="ALPHACO", isin=ALPHA)
    for field in ("name", "asset_type", "market_session"):
        base.pop(field)
    return imported, base


@pytest.mark.parametrize(
    "fees",
    [
        pytest.param({"taxes": "0"}, id="omitted-brokerage_fee"),
        pytest.param({"brokerage_fee": "0"}, id="omitted-taxes"),
        pytest.param({"brokerage_fee": None, "taxes": "0"}, id="null-brokerage_fee"),
        pytest.param({"brokerage_fee": "0", "taxes": None}, id="null-taxes"),
        pytest.param({}, id="both-omitted"),
        pytest.param({"brokerage_fee": None, "taxes": None}, id="both-null"),
    ],
)
def test_correcting_unprovided_charges_rejects_any_missing_or_null_fee(client, fees):
    imported, base = _imported_correction_base(client)
    resp = client.post(f"/trades/{imported['id']}/correct", json={**base, **fees})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_trade"
    assert "must both be stated" in resp.json()["detail"]["message"]
    assert len(client.get("/trades").json()) == 1  # nothing was written; omitted/null is never read as zero


def test_explicit_zero_for_both_fees_is_known_zero_and_the_correction_affirms_charges(client):
    imported, base = _imported_correction_base(client)
    resp = client.post(f"/trades/{imported['id']}/correct", json={**base, "brokerage_fee": "0", "taxes": "0"})
    assert resp.status_code == 201
    fixed = resp.json()
    assert (fixed["brokerage_fee"], fixed["taxes"], fixed["charges_provided"]) == ("0.000000", "0.000000", True)
    assert imported["charges_provided"] is False  # the imported original keeps "charges not provided"
    (original, corrected) = sorted(client.get("/trades").json(), key=lambda t: t["recorded_at"])
    assert (original["charges_provided"], corrected["charges_provided"]) == (False, True)


def test_nonzero_fees_are_accepted_as_stated_and_not_rewritten_to_zero(client):
    imported, base = _imported_correction_base(client)
    fixed = client.post(f"/trades/{imported['id']}/correct", json={**base, "brokerage_fee": "1.5", "taxes": "0.25"}).json()
    assert (fixed["brokerage_fee"], fixed["taxes"], fixed["charges_provided"]) == ("1.500000", "0.250000", True)


def test_a_listing_from_an_earlier_fully_exited_position_stays_visible_for_a_later_position(client):
    client.post("/trades", json=body(quantity="5", trade_timestamp="2026-01-01T10:00:00Z"))  # NSE
    client.post("/trades", json=body(side="SELL", quantity="5", trade_timestamp="2026-01-02T10:00:00Z"))  # full exit
    assert client.get("/portfolio/holdings").json() == []
    client.post("/trades", json=body(exchange="BSE", quantity="2", trade_timestamp="2026-01-03T10:00:00Z"))
    (h,) = client.get("/portfolio/holdings").json()
    assert (h["quantity"], h["invested_amount"]) == ("2.000000", "200.000000")  # the position is only the new epoch
    assert h["listings"] == [{"symbol": "RELIANCE", "exchange": "BSE"}, {"symbol": "RELIANCE", "exchange": "NSE"}]
    (before,) = client.get("/portfolio/holdings", params={"as_of": "2026-01-01T12:00:00Z"}).json()
    assert before["listings"] == [{"symbol": "RELIANCE", "exchange": "NSE"}]  # as_of limits the metadata too
