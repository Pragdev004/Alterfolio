from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)
from app.schemas.trade import TradeCreate
from app.services.position_accounting_service import OversellError
from app.services.trade_service import TradeService


USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def _build_trade_payload(*, transaction_type: TransactionType, quantity: str, price: str) -> TradeCreate:
    return TradeCreate(
        user_id=USER_ID,
        asset_symbol="TCS",
        asset_name="Tata Consultancy Services",
        asset_type=AssetType.STOCK,
        exchange=Exchange.NSE,
        currency=Currency.INR,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        price_per_unit=Decimal(price),
        trade_timestamp=datetime.now(timezone.utc),
        brokerage_fee=Decimal("0"),
        taxes=Decimal("0"),
        trade_source=TradeSource.MANUAL,
        market_session=MarketSession.REGULAR,
        status=TradeStatus.EXECUTED,
    )


def _build_created_trade(trade: TradeCreate) -> SimpleNamespace:
    payload = trade.model_dump(exclude={"user_id"})
    return SimpleNamespace(user_id=USER_ID, **payload)


def _build_service() -> tuple[TradeService, Mock, Mock, Mock]:
    db = Mock()
    trade_repository = Mock()
    position_repository = Mock()

    service = TradeService(
        db=db,
        trade_repository=trade_repository,
        position_repository=position_repository,
    )
    return service, db, trade_repository, position_repository


def test_executed_buy_creates_trade_and_updates_position_in_single_transaction() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="150",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("2"),
        remaining_cost_basis=Decimal("200"),
        cumulative_realized_profit_loss=Decimal("10"),
    )
    position_repository.lock_position.return_value = existing_position

    service.create_trade(trade, USER_ID)

    trade_repository.create.assert_called_once_with(trade, USER_ID)
    position_repository.lock_position.assert_called_once()
    position_repository.upsert_position.assert_called_once()

    upsert_kwargs = position_repository.upsert_position.call_args.kwargs
    assert upsert_kwargs["remaining_quantity"] == Decimal("3")
    assert upsert_kwargs["remaining_cost_basis"] == Decimal("350")
    assert upsert_kwargs["average_cost"] == Decimal("350") / Decimal("3")
    assert upsert_kwargs["cumulative_realized_profit_loss"] == Decimal("10")

    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_executed_sell_updates_position_and_realized_pl_in_single_transaction() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.SELL,
        quantity="4",
        price="120",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("10"),
        remaining_cost_basis=Decimal("1000"),
        cumulative_realized_profit_loss=Decimal("50"),
    )
    position_repository.lock_position.return_value = existing_position

    service.create_trade(trade, USER_ID)

    upsert_kwargs = position_repository.upsert_position.call_args.kwargs
    assert upsert_kwargs["remaining_quantity"] == Decimal("6")
    assert upsert_kwargs["remaining_cost_basis"] == Decimal("600")
    assert upsert_kwargs["average_cost"] == Decimal("100")
    assert upsert_kwargs["cumulative_realized_profit_loss"] == Decimal("130")

    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_executed_sell_oversell_rolls_back_trade_and_position_updates() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.SELL,
        quantity="6",
        price="120",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("5"),
        remaining_cost_basis=Decimal("500"),
        cumulative_realized_profit_loss=Decimal("50"),
    )
    position_repository.lock_position.return_value = existing_position

    with pytest.raises(OversellError):
        service.create_trade(trade, USER_ID)

    position_repository.upsert_position.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_called_once()
