from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

from app.models.enums import (
    AssetType,
    Exchange,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)
from app.schemas.trade import TradeCreate
from app.services.portfolio_service import PortfolioService
from app.services.trade_service import TradeService


AUTH_USER = UUID("11111111-1111-4111-8111-111111111111")
PAYLOAD_USER = UUID("22222222-2222-4222-8222-222222222222")


def _build_trade_payload() -> TradeCreate:
    return TradeCreate(
        user_id=PAYLOAD_USER,
        asset_symbol="TCS",
        asset_name="Tata Consultancy Services",
        asset_type=AssetType.STOCK,
        exchange=Exchange.NSE,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("1"),
        price_per_unit=Decimal("100"),
        trade_timestamp=datetime.now(timezone.utc),
        trade_source=TradeSource.MANUAL,
        market_session=MarketSession.REGULAR,
    )


def _build_trade_service() -> tuple[TradeService, Mock, Mock, Mock]:
    db = Mock()
    trade_repository = Mock()
    position_repository = Mock()

    service = TradeService(
        db=db,
        trade_repository=trade_repository,
        position_repository=position_repository,
    )
    return service, db, trade_repository, position_repository


def test_trade_service_create_uses_authenticated_user_identity() -> None:
    service, db, trade_repository, position_repository = _build_trade_service()
    trade_repository.create.return_value = SimpleNamespace(status=TradeStatus.PENDING)

    trade = _build_trade_payload()
    service.create_trade(trade, AUTH_USER)

    trade_repository.create.assert_called_once_with(trade, AUTH_USER)
    position_repository.lock_position.assert_not_called()
    db.commit.assert_called_once()


def test_trade_service_scopes_get_and_list_queries() -> None:
    service, _, trade_repository, _ = _build_trade_service()

    trade_id = UUID("33333333-3333-4333-8333-333333333333")
    service.get_trade(trade_id, AUTH_USER)
    service.list_trades(AUTH_USER)

    trade_repository.get_by_id.assert_called_once_with(trade_id, AUTH_USER)
    trade_repository.list_all.assert_called_once_with(AUTH_USER)


def test_portfolio_service_scopes_summary_query() -> None:
    repository = Mock()
    service = PortfolioService(repository)

    service.get_summary(AUTH_USER)

    repository.get_summary.assert_called_once_with(AUTH_USER)
