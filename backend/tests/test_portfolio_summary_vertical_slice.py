from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import app.models.position  # noqa: F401
import app.models.trade  # noqa: F401
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_authenticated_user_id
from app.api.router import api_router
from app.api.routes import portfolio as portfolio_routes
from app.api.routes import trades as trades_routes
from app.db.database import get_db
from app.models.base import Base
from app.models.enums import AssetType, Currency, Exchange
from app.models.position import Position
from app.models.trade import Trade
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository
from app.services.portfolio_service import PortfolioService
from app.services.trade_service import TradeService


USER_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class StubMarketService:
    def __init__(self, quotes: dict[str, dict[str, object]] | None = None):
        self.quotes = quotes or {}
        self.called_symbols: list[str] = []

    def get_stock_quote(self, symbol: str):
        self.called_symbols.append(symbol)
        quote = self.quotes.get(symbol)
        if quote is None:
            raise RuntimeError("quote unavailable")

        if isinstance(quote, Exception):
            raise quote

        return SimpleNamespace(
            symbol=quote.get("symbol", symbol),
            currency=quote.get("currency", "INR"),
            current_price=quote.get("current_price"),
        )


def _position(
    *,
    symbol: str,
    exchange: Exchange,
    asset_type: AssetType = AssetType.STOCK,
    currency: Currency = Currency.INR,
    quantity: str = "1",
    cost_basis: str = "100",
    average_cost: str = "100",
    realized: str = "0",
) -> SimpleNamespace:
    return SimpleNamespace(
        asset_symbol=symbol,
        remaining_quantity=Decimal(quantity),
        remaining_cost_basis=Decimal(cost_basis),
        average_cost=Decimal(average_cost),
        cumulative_realized_profit_loss=Decimal(realized),
        exchange=exchange,
        asset_type=asset_type,
        currency=currency,
    )


def _build_service(
    *,
    total_trades: int,
    active_positions: list[SimpleNamespace],
    all_positions: list[SimpleNamespace],
    market_service: StubMarketService,
) -> PortfolioService:
    portfolio_repository = SimpleNamespace(get_total_trades=lambda user_id: total_trades)
    position_repository = SimpleNamespace(
        list_active_positions=lambda **kwargs: active_positions,
        list_all_positions=lambda **kwargs: all_positions,
    )

    return PortfolioService(
        portfolio_repository=portfolio_repository,
        position_repository=position_repository,
        market_service=market_service,
    )


class SqlitePositionRepository(PositionRepository):
    def upsert_position(
        self,
        *,
        user_id,
        asset_symbol,
        exchange,
        asset_type,
        currency,
        remaining_quantity,
        remaining_cost_basis,
        average_cost,
        cumulative_realized_profit_loss,
        last_accounted_trade_timestamp,
    ):
        position = self.get_position(
            user_id=user_id,
            asset_symbol=asset_symbol,
            exchange=exchange,
            asset_type=asset_type,
            currency=currency,
        )

        if position is None:
            position = Position(
                user_id=user_id,
                asset_symbol=asset_symbol,
                exchange=exchange,
                asset_type=asset_type,
                currency=currency,
                remaining_quantity=remaining_quantity,
                remaining_cost_basis=remaining_cost_basis,
                average_cost=average_cost,
                cumulative_realized_profit_loss=cumulative_realized_profit_loss,
                last_accounted_trade_timestamp=last_accounted_trade_timestamp,
            )
            self.db.add(position)
        else:
            position.remaining_quantity = remaining_quantity
            position.remaining_cost_basis = remaining_cost_basis
            position.average_cost = average_cost
            position.cumulative_realized_profit_loss = cumulative_realized_profit_loss
            position.last_accounted_trade_timestamp = last_accounted_trade_timestamp

        self.db.flush()
        return position


class SqliteTradeRepository(TradeRepository):
    def create(self, trade, user_id):
        trade_data = trade.model_dump(exclude={"user_id"})
        db_trade = Trade(**trade_data, user_id=user_id)

        self.db.add(db_trade)
        self.db.flush()

        return db_trade


def _build_app(market_service: StubMarketService) -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(api_router)

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def _override_authenticated_user_id(request: Request) -> UUID:
        return UUID(request.headers.get("X-User-Id", ""))

    def _override_portfolio_service(db: Session = Depends(get_db)) -> PortfolioService:
        return PortfolioService(
            portfolio_repository=PortfolioRepository(db),
            position_repository=SqlitePositionRepository(db),
            market_service=market_service,
        )

    def _override_trade_service(db: Session = Depends(get_db)) -> TradeService:
        return TradeService(
            db=db,
            trade_repository=SqliteTradeRepository(db),
            position_repository=SqlitePositionRepository(db),
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_authenticated_user_id] = _override_authenticated_user_id
    app.dependency_overrides[portfolio_routes.get_portfolio_service] = _override_portfolio_service
    app.dependency_overrides[trades_routes.get_trade_service] = _override_trade_service

    return TestClient(app), session_factory


def _create_trade(
    client: TestClient,
    *,
    user_id: UUID,
    symbol: str,
    exchange: str,
    transaction_type: str,
    quantity: str,
    price: str,
) -> dict:
    payload = {
        "user_id": str(user_id),
        "asset_symbol": symbol,
        "asset_name": f"{symbol} Ltd",
        "asset_type": "STOCK",
        "exchange": exchange,
        "currency": "INR",
        "transaction_type": transaction_type,
        "quantity": quantity,
        "price_per_unit": price,
        "trade_timestamp": datetime.now(timezone.utc).isoformat(),
        "trade_source": "MANUAL",
        "market_session": "REGULAR",
        "status": "EXECUTED",
    }

    response = client.post("/trades/", headers={"X-User-Id": str(user_id)}, json=payload)
    assert response.status_code == 201
    return response.json()


def _list_positions(session_factory: sessionmaker, user_id: UUID) -> list[Position]:
    with session_factory() as db:
        return (
            db.query(Position)
            .filter(Position.user_id == user_id)
            .order_by(Position.asset_symbol.asc())
            .all()
        )


def _get_summary(client: TestClient, user_id: UUID) -> dict:
    response = client.get("/portfolio/summary", headers={"X-User-Id": str(user_id)})
    assert response.status_code == 200
    return response.json()


def test_nse_quote_resolution_uses_ns_suffix() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {"current_price": "120", "symbol": "RELIANCE.NS", "currency": "INR"}
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert market_service.called_symbols == ["RELIANCE.NS"]
    assert summary.holdings[0].current_price == Decimal("120")


def test_bse_quote_resolution_uses_bo_suffix() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.BSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.BO": {"current_price": "121", "symbol": "RELIANCE.BO", "currency": "INR"}
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert market_service.called_symbols == ["RELIANCE.BO"]
    assert summary.holdings[0].current_price == Decimal("121")


def test_same_symbol_across_nse_and_bse_remains_distinct() -> None:
    active = [
        _position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100"),
        _position(symbol="RELIANCE", exchange=Exchange.BSE, quantity="1", cost_basis="100"),
    ]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {"current_price": "120", "symbol": "RELIANCE.NS", "currency": "INR"},
            "RELIANCE.BO": {"current_price": "121", "symbol": "RELIANCE.BO", "currency": "INR"},
        }
    )
    service = _build_service(
        total_trades=2,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert market_service.called_symbols == ["RELIANCE.NS", "RELIANCE.BO"]
    assert len(summary.holdings) == 2

    nse_holding = next(holding for holding in summary.holdings if holding.exchange == "NSE")
    bse_holding = next(holding for holding in summary.holdings if holding.exchange == "BSE")
    assert nse_holding.current_price == Decimal("120")
    assert bse_holding.current_price == Decimal("121")


def test_unsupported_exchange_is_marked_unavailable() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.MCX, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {"current_price": "120", "symbol": "RELIANCE.NS", "currency": "INR"}
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert market_service.called_symbols == []
    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_unsupported_asset_type_is_marked_unavailable() -> None:
    active = [
        _position(
            symbol="NIFTYBEES",
            exchange=Exchange.NSE,
            asset_type=AssetType.ETF,
            quantity="1",
            cost_basis="100",
        )
    ]
    market_service = StubMarketService(
        quotes={
            "NIFTYBEES.NS": {"current_price": "200", "symbol": "NIFTYBEES.NS", "currency": "INR"}
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert market_service.called_symbols == []
    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_quote_identity_mismatch_is_rejected_when_provider_symbol_is_different_instrument() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.BSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.BO": {
                "current_price": "120",
                "symbol": "INFY",
                "currency": "INR",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_quote_identity_mismatch_is_rejected_when_provider_symbol_is_different_exchange() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "RELIANCE.BO",
                "currency": "INR",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_quote_currency_mismatch_is_rejected_without_fabricated_valuation() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "RELIANCE.NS",
                "currency": "USD",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.total_market_value is None
    assert summary.total_unrealized_profit_loss is None
    assert summary.holdings[0].quote_status == "UNAVAILABLE"
    assert summary.holdings[0].market_value is None
    assert summary.holdings[0].unrealized_profit_loss is None


def test_quote_identity_match_is_accepted() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "RELIANCE.NS",
                "currency": "INR",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "COMPLETE"
    assert summary.holdings[0].quote_status == "AVAILABLE"


def test_quote_identity_absent_does_not_invent_identity_confirmation() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "",
                "currency": "INR",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"
    assert summary.holdings[0].current_price is None


def test_quote_with_none_symbol_is_rejected() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": None,
                "currency": "INR",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_quote_with_blank_currency_is_rejected() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "RELIANCE.NS",
                "currency": "",
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_quote_with_none_currency_is_rejected() -> None:
    active = [_position(symbol="RELIANCE", exchange=Exchange.NSE, quantity="1", cost_basis="100")]
    market_service = StubMarketService(
        quotes={
            "RELIANCE.NS": {
                "current_price": "120",
                "symbol": "RELIANCE.NS",
                "currency": None,
            }
        }
    )
    service = _build_service(
        total_trades=1,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    summary = service.get_summary(USER_A)

    assert summary.valuation_status == "UNAVAILABLE"
    assert summary.holdings[0].quote_status == "UNAVAILABLE"


def test_partial_quote_status_contract_is_stable() -> None:
    active = [
        _position(symbol="TCS", exchange=Exchange.NSE, quantity="2", cost_basis="200"),
        _position(symbol="INFY", exchange=Exchange.NSE, quantity="1", cost_basis="100"),
    ]
    market_service = StubMarketService(
        quotes={"TCS.NS": {"current_price": "110", "symbol": "TCS.NS", "currency": "INR"}}
    )
    service = _build_service(
        total_trades=2,
        active_positions=active,
        all_positions=active,
        market_service=market_service,
    )

    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")
    app.dependency_overrides[portfolio_routes.get_portfolio_service] = lambda: service

    client = TestClient(app)
    response = client.get("/portfolio/summary", headers={"X-User-Id": str(USER_A)})

    assert response.status_code == 200
    body = response.json()
    assert body["valuation_status"] == "PARTIAL"
    assert body["total_market_value"] is None
    assert body["total_unrealized_profit_loss"] is None
    assert {holding["quote_status"] for holding in body["holdings"]} == {"AVAILABLE", "UNAVAILABLE"}


def test_buy_partial_sell_complete_sell_math_is_reflected_in_summary() -> None:
    market_service = StubMarketService(
        quotes={"TCS.NS": {"current_price": "120", "symbol": "TCS.NS", "currency": "INR"}}
    )

    partial_position = _position(
        symbol="TCS",
        exchange=Exchange.NSE,
        quantity="6",
        cost_basis="600",
        average_cost="100",
        realized="100",
    )
    service = _build_service(
        total_trades=2,
        active_positions=[partial_position],
        all_positions=[partial_position],
        market_service=market_service,
    )

    partial_summary = service.get_summary(USER_A)
    holding = partial_summary.holdings[0]
    assert holding.quantity == Decimal("6")
    assert holding.invested_amount == Decimal("600")
    assert holding.realized_profit_loss == Decimal("100")
    assert holding.market_value == Decimal("720")
    assert holding.unrealized_profit_loss == Decimal("120")
    assert partial_summary.total_realized_profit_loss == Decimal("100")

    closed_position = _position(
        symbol="TCS",
        exchange=Exchange.NSE,
        quantity="0",
        cost_basis="0",
        average_cost="0",
        realized="160",
    )
    closed_service = _build_service(
        total_trades=3,
        active_positions=[],
        all_positions=[closed_position],
        market_service=market_service,
    )

    closed_summary = closed_service.get_summary(USER_A)
    assert closed_summary.holdings == []
    assert closed_summary.total_realized_profit_loss == Decimal("160")
    assert closed_summary.total_market_value is None


def test_summary_repositories_are_scoped_to_authenticated_user() -> None:
    portfolio_calls: list[UUID] = []
    active_calls: list[UUID] = []
    all_calls: list[UUID] = []

    def _total_trades(user_id):
        portfolio_calls.append(user_id)
        return 1

    def _active_positions(*, user_id):
        active_calls.append(user_id)
        if user_id == USER_A:
            return [_position(symbol="TCS", exchange=Exchange.NSE)]
        return [_position(symbol="INFY", exchange=Exchange.NSE)]

    def _all_positions(*, user_id):
        all_calls.append(user_id)
        if user_id == USER_A:
            return [_position(symbol="TCS", exchange=Exchange.NSE)]
        return [_position(symbol="INFY", exchange=Exchange.NSE)]

    service = PortfolioService(
        portfolio_repository=SimpleNamespace(get_total_trades=_total_trades),
        position_repository=SimpleNamespace(
            list_active_positions=_active_positions,
            list_all_positions=_all_positions,
        ),
        market_service=StubMarketService(
            quotes={
                "TCS.NS": {"current_price": "120", "symbol": "TCS.NS", "currency": "INR"},
                "INFY.NS": {"current_price": "150", "symbol": "INFY.NS", "currency": "INR"},
            }
        ),
    )

    summary_a = service.get_summary(USER_A)
    summary_b = service.get_summary(USER_B)

    assert summary_a.holdings[0].symbol == "TCS"
    assert summary_b.holdings[0].symbol == "INFY"
    assert portfolio_calls == [USER_A, USER_B]
    assert active_calls == [USER_A, USER_B]
    assert all_calls == [USER_A, USER_B]


def test_real_buy_trade_updates_position_and_summary_valuation() -> None:
    client, session_factory = _build_app(
        StubMarketService(
            quotes={"TCS.NS": {"current_price": "120", "symbol": "TCS.NS", "currency": "INR"}}
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="BUY",
        quantity="10",
        price="100",
    )

    positions = _list_positions(session_factory, USER_A)
    assert len(positions) == 1
    assert positions[0].remaining_quantity == Decimal("10")
    assert positions[0].remaining_cost_basis == Decimal("1000")

    summary = _get_summary(client, USER_A)
    assert summary["valuation_status"] == "COMPLETE"
    assert summary["total_trades"] == 1
    assert summary["holdings"][0]["quantity"] == "10.00000000"
    assert summary["holdings"][0]["invested_amount"] == "1000.00000000"
    assert summary["holdings"][0]["market_value"] == "1200.00000000"


def test_symbol_canonicalization_merges_case_and_known_exchange_suffix_for_position_identity() -> None:
    client, session_factory = _build_app(
        StubMarketService(
            quotes={"TCS.NS": {"current_price": "125", "symbol": "TCS.NS", "currency": "INR"}}
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="tcs",
        exchange="NSE",
        transaction_type="BUY",
        quantity="2",
        price="100",
    )
    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS.NS",
        exchange="NSE",
        transaction_type="BUY",
        quantity="3",
        price="110",
    )
    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="SELL",
        quantity="1",
        price="120",
    )

    positions = _list_positions(session_factory, USER_A)
    assert len(positions) == 1
    assert positions[0].asset_symbol == "TCS"
    assert positions[0].exchange == Exchange.NSE
    assert positions[0].remaining_quantity == Decimal("4")

    summary = _get_summary(client, USER_A)
    assert summary["holdings"][0]["symbol"] == "TCS"
    assert summary["holdings"][0]["exchange"] == "NSE"


def test_symbol_canonicalization_preserves_legitimate_periods_not_matching_known_suffixes() -> None:
    client, session_factory = _build_app(
        StubMarketService(
            quotes={"BRK.B.NS": {"current_price": "300", "symbol": "BRK.B.NS", "currency": "INR"}}
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="brk.b",
        exchange="NSE",
        transaction_type="BUY",
        quantity="1",
        price="250",
    )

    positions = _list_positions(session_factory, USER_A)
    assert len(positions) == 1
    assert positions[0].asset_symbol == "BRK.B"

    summary = _get_summary(client, USER_A)
    assert summary["valuation_status"] == "COMPLETE"
    assert summary["holdings"][0]["symbol"] == "BRK.B"


def test_real_partial_sell_updates_remaining_position_and_realized_pl() -> None:
    client, session_factory = _build_app(
        StubMarketService(
            quotes={"TCS.NS": {"current_price": "125", "symbol": "TCS.NS", "currency": "INR"}}
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="BUY",
        quantity="10",
        price="100",
    )
    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="SELL",
        quantity="4",
        price="130",
    )

    positions = _list_positions(session_factory, USER_A)
    assert len(positions) == 1
    assert positions[0].remaining_quantity == Decimal("6")
    assert positions[0].remaining_cost_basis == Decimal("600")
    assert positions[0].cumulative_realized_profit_loss == Decimal("120")

    summary = _get_summary(client, USER_A)
    assert summary["holdings"][0]["quantity"] == "6.00000000"
    assert summary["holdings"][0]["invested_amount"] == "600.00000000"
    assert summary["holdings"][0]["realized_profit_loss"] == "120.00000000"
    assert summary["total_realized_profit_loss"] == "120.00000000"


def test_real_complete_sell_closes_position_and_retains_realized_pl() -> None:
    client, session_factory = _build_app(
        StubMarketService(
            quotes={"TCS.NS": {"current_price": "110", "symbol": "TCS.NS", "currency": "INR"}}
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="BUY",
        quantity="5",
        price="100",
    )
    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="SELL",
        quantity="5",
        price="110",
    )

    positions = _list_positions(session_factory, USER_A)
    assert len(positions) == 1
    assert positions[0].remaining_quantity == Decimal("0")
    assert positions[0].remaining_cost_basis == Decimal("0")
    assert positions[0].cumulative_realized_profit_loss == Decimal("50")

    summary = _get_summary(client, USER_A)
    assert summary["valuation_status"] == "UNAVAILABLE"
    assert summary["holdings"] == []
    assert summary["total_realized_profit_loss"] == "50.00000000"


def test_real_trade_position_summary_flow_isolated_across_two_users() -> None:
    client, _ = _build_app(
        StubMarketService(
            quotes={
                "TCS.NS": {"current_price": "120", "symbol": "TCS.NS", "currency": "INR"},
                "INFY.NS": {"current_price": "200", "symbol": "INFY.NS", "currency": "INR"},
            }
        )
    )

    _create_trade(
        client,
        user_id=USER_A,
        symbol="TCS",
        exchange="NSE",
        transaction_type="BUY",
        quantity="2",
        price="100",
    )
    _create_trade(
        client,
        user_id=USER_B,
        symbol="INFY",
        exchange="NSE",
        transaction_type="BUY",
        quantity="3",
        price="150",
    )

    summary_a = _get_summary(client, USER_A)
    summary_b = _get_summary(client, USER_B)

    assert summary_a["total_trades"] == 1
    assert summary_a["holdings"][0]["symbol"] == "TCS"
    assert summary_b["total_trades"] == 1
    assert summary_b["holdings"][0]["symbol"] == "INFY"


def test_portfolio_summary_logs_safe_metadata_on_service_failure() -> None:
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")

    class FailingPortfolioService:
        def get_summary(self, user_id):
            raise RuntimeError("db exploded")

    app.dependency_overrides[portfolio_routes.get_portfolio_service] = (
        lambda: FailingPortfolioService()
    )

    client = TestClient(app)

    with patch.object(portfolio_routes, "logger") as logger:
        response = client.get("/portfolio/summary", headers={"X-User-Id": str(USER_A)})

    assert response.status_code == 500
    logger.error.assert_called_once_with(
        "portfolio.summary.error",
        extra={
            "route": "/portfolio/summary",
            "error_code": "portfolio_summary_failed",
        },
    )


def test_portfolio_summary_returns_stable_error_contract_for_service_failure() -> None:
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")

    class FailingPortfolioService:
        def get_summary(self, user_id):
            raise RuntimeError("db exploded")

    app.dependency_overrides[portfolio_routes.get_portfolio_service] = (
        lambda: FailingPortfolioService()
    )

    client = TestClient(app)
    response = client.get("/portfolio/summary", headers={"X-User-Id": str(USER_A)})

    assert response.status_code == 500
    assert response.json() == {
        "code": "portfolio_summary_failed",
        "message": "Failed to retrieve portfolio summary",
    }
