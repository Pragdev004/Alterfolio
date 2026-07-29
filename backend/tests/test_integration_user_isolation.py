from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.router import api_router
from app.api.routes import portfolio as portfolio_routes
from app.api.routes import trades as trades_routes
from app.models.enums import TransactionType
from app.schemas.portfolio import HoldingSummary, PortfolioSummary
from app.schemas.trade import TradeCreate, TradeResponse


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


def _build_trade_payload(user_id: UUID, symbol: str, quantity: str = "1", price: str = "100") -> dict:
    return {
        "user_id": str(user_id),
        "asset_symbol": symbol,
        "asset_name": f"{symbol} Ltd",
        "asset_type": "STOCK",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": quantity,
        "price_per_unit": price,
        "trade_timestamp": datetime.now(timezone.utc).isoformat(),
        "trade_source": "MANUAL",
        "market_session": "REGULAR",
    }


class InMemoryTradeService:
    def __init__(self) -> None:
        self._trades: list[TradeResponse] = []

    def create_trade(self, trade: TradeCreate, user_id: UUID) -> TradeResponse:
        now = datetime.now(timezone.utc)
        created = TradeResponse(
            id=uuid4(),
            user_id=user_id,
            created_at=now,
            updated_at=now,
            **trade.model_dump(exclude={"user_id"}),
        )
        self._trades.append(created)
        return created

    def list_trades(self, user_id: UUID) -> list[TradeResponse]:
        return [trade for trade in self._trades if trade.user_id == user_id]

    def get_trade(self, trade_id: UUID, user_id: UUID) -> TradeResponse | None:
        for trade in self._trades:
            if trade.id == trade_id and trade.user_id == user_id:
                return trade
        return None


class InMemoryPortfolioService:
    def __init__(self, trade_service: InMemoryTradeService) -> None:
        self._trade_service = trade_service

    def get_summary(self, user_id: UUID) -> PortfolioSummary:
        user_trades = self._trade_service.list_trades(user_id)

        holdings_agg = defaultdict(lambda: {"quantity": Decimal("0"), "invested": Decimal("0")})
        for trade in user_trades:
            if trade.transaction_type != TransactionType.BUY:
                continue
            holdings_agg[trade.asset_symbol]["quantity"] += trade.quantity
            holdings_agg[trade.asset_symbol]["invested"] += trade.quantity * trade.price_per_unit

        holdings: list[HoldingSummary] = []
        for symbol, values in holdings_agg.items():
            quantity = values["quantity"]
            invested = values["invested"]
            average = invested / quantity if quantity else Decimal("0")
            holdings.append(
                HoldingSummary(
                    symbol=symbol,
                    quantity=quantity,
                    average_buy_price=average,
                    invested_amount=invested,
                )
            )

        total_invested = sum((holding.invested_amount for holding in holdings), Decimal("0"))
        return PortfolioSummary(
            total_trades=len(user_trades),
            total_invested=total_invested,
            holdings=holdings,
        )


def _build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(api_router)

    trade_service = InMemoryTradeService()
    portfolio_service = InMemoryPortfolioService(trade_service)

    app.dependency_overrides[trades_routes.get_trade_service] = lambda: trade_service
    app.dependency_overrides[portfolio_routes.get_portfolio_service] = lambda: portfolio_service

    return TestClient(app)


def test_user_cannot_list_or_retrieve_another_users_trades() -> None:
    client = _build_test_client()

    create_for_user_a = client.post(
        "/trades/",
        headers={"X-User-Id": str(USER_A)},
        json=_build_trade_payload(USER_B, "TCS"),
    )
    assert create_for_user_a.status_code == 201
    trade_a = create_for_user_a.json()

    create_for_user_b = client.post(
        "/trades/",
        headers={"X-User-Id": str(USER_B)},
        json=_build_trade_payload(USER_A, "INFY"),
    )
    assert create_for_user_b.status_code == 201
    trade_b = create_for_user_b.json()

    assert trade_a["user_id"] == str(USER_A)
    assert trade_b["user_id"] == str(USER_B)

    list_for_user_a = client.get(
        "/trades/",
        headers={"X-User-Id": str(USER_A)},
    )
    assert list_for_user_a.status_code == 200
    trades_for_user_a = list_for_user_a.json()
    assert len(trades_for_user_a) == 1
    assert trades_for_user_a[0]["id"] == trade_a["id"]

    get_other_users_trade = client.get(
        f"/trades/{trade_b['id']}",
        headers={"X-User-Id": str(USER_A)},
    )
    assert get_other_users_trade.status_code == 404


def test_user_cannot_see_another_users_portfolio() -> None:
    client = _build_test_client()

    create_for_user_a = client.post(
        "/trades/",
        headers={"X-User-Id": str(USER_A)},
        json=_build_trade_payload(USER_B, "TCS", quantity="2", price="100"),
    )
    assert create_for_user_a.status_code == 201

    create_for_user_b = client.post(
        "/trades/",
        headers={"X-User-Id": str(USER_B)},
        json=_build_trade_payload(USER_A, "INFY", quantity="3", price="200"),
    )
    assert create_for_user_b.status_code == 201

    summary_for_user_a = client.get(
        "/portfolio/summary",
        headers={"X-User-Id": str(USER_A)},
    )
    assert summary_for_user_a.status_code == 200

    body = summary_for_user_a.json()
    assert body["total_trades"] == 1
    assert body["total_invested"] == "200"
    assert len(body["holdings"]) == 1
    assert body["holdings"][0]["symbol"] == "TCS"


def test_development_fallback_principal_keeps_existing_flows_working() -> None:
    client = _build_test_client()

    create_trade = client.post(
        "/trades/",
        json=_build_trade_payload(USER_B, "HDFCBANK"),
    )
    assert create_trade.status_code == 201

    created_trade = create_trade.json()
    assert created_trade["user_id"] == str(USER_A)

    list_trades = client.get("/trades/")
    assert list_trades.status_code == 200
    assert len(list_trades.json()) == 1
