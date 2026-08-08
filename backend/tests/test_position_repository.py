from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

from app.models.enums import AssetType, Currency, Exchange
from app.models.position import Position
from app.repositories.position_repository import PositionRepository


USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_upsert_position_creates_new_position() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    timestamp = datetime.now(timezone.utc)

    created = repository.upsert_position(
        user_id=USER_ID,
        asset_symbol="TCS",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        remaining_quantity=Decimal("10"),
        remaining_cost_basis=Decimal("1000"),
        average_cost=Decimal("100"),
        cumulative_realized_profit_loss=Decimal("0"),
        last_accounted_trade_timestamp=timestamp,
    )

    assert isinstance(created, Position)
    assert created.user_id == USER_ID
    assert created.asset_symbol == "TCS"
    assert created.exchange == Exchange.NSE
    assert created.asset_type == AssetType.STOCK
    assert created.currency == Currency.INR
    assert created.remaining_quantity == Decimal("10")
    assert created.remaining_cost_basis == Decimal("1000")
    assert created.average_cost == Decimal("100")
    assert created.cumulative_realized_profit_loss == Decimal("0")
    assert created.last_accounted_trade_timestamp == timestamp

    db.add.assert_called_once_with(created)
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(created)


def test_upsert_position_updates_existing_position() -> None:
    existing = Position(
        user_id=USER_ID,
        asset_symbol="TCS",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        remaining_quantity=Decimal("10"),
        remaining_cost_basis=Decimal("1000"),
        average_cost=Decimal("100"),
        cumulative_realized_profit_loss=Decimal("0"),
        last_accounted_trade_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    query = Mock()
    query.filter.return_value = query
    query.first.return_value = existing

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    updated_timestamp = datetime.now(timezone.utc)

    updated = repository.upsert_position(
        user_id=USER_ID,
        asset_symbol="TCS",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        remaining_quantity=Decimal("8"),
        remaining_cost_basis=Decimal("820"),
        average_cost=Decimal("102.5"),
        cumulative_realized_profit_loss=Decimal("35"),
        last_accounted_trade_timestamp=updated_timestamp,
    )

    assert updated is existing
    assert updated.remaining_quantity == Decimal("8")
    assert updated.remaining_cost_basis == Decimal("820")
    assert updated.average_cost == Decimal("102.5")
    assert updated.cumulative_realized_profit_loss == Decimal("35")
    assert updated.last_accounted_trade_timestamp == updated_timestamp

    db.add.assert_not_called()
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(existing)


def test_list_active_positions_filters_positive_quantity() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    repository.list_active_positions(user_id=USER_ID)

    filter_args = query.filter.call_args.args
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_ID
        for arg in filter_args
    )
    assert any(getattr(arg.left, "name", "") == "remaining_quantity" for arg in filter_args)


def test_get_position_retrieves_by_user_and_instrument_identity() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    repository.get_position(
        user_id=USER_ID,
        asset_symbol="INFY",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
    )

    filter_args = query.filter.call_args.args
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_ID
        for arg in filter_args
    )
    assert any(
        getattr(arg.left, "name", "") == "asset_symbol" and arg.right.value == "INFY"
        for arg in filter_args
    )
    assert any(
        getattr(arg.left, "name", "") == "exchange" and arg.right.value == Exchange.NSE
        for arg in filter_args
    )
    assert any(
        getattr(arg.left, "name", "") == "asset_type" and arg.right.value == AssetType.STOCK
        for arg in filter_args
    )
    assert any(
        getattr(arg.left, "name", "") == "currency" and arg.right.value == Currency.INR
        for arg in filter_args
    )


def test_lock_position_applies_row_level_lock() -> None:
    query = Mock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    repository.lock_position(
        user_id=USER_ID,
        asset_symbol="RELIANCE",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
    )

    query.with_for_update.assert_called_once_with()


def test_list_all_positions_scopes_to_user() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = PositionRepository(db)
    repository.list_all_positions(user_id=USER_ID)

    filter_args = query.filter.call_args.args
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_ID
        for arg in filter_args
    )
