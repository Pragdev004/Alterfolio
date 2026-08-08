from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

from app.models.enums import AssetType, Currency, Exchange
from app.models.market_snapshot import MarketSnapshot
from app.repositories.market_snapshot_repository import MarketSnapshotRepository


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")


def _build_snapshot(*, user_id: UUID = USER_A, symbol: str = "AAPL") -> MarketSnapshot:
    return MarketSnapshot(
        id=SNAPSHOT_ID,
        user_id=user_id,
        captured_at=datetime.now(timezone.utc),
        source="MANUAL_CAPTURE",
        asset_symbol=symbol,
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        asset_price=Decimal("195.25000000"),
        price_timestamp=datetime.now(timezone.utc),
        volume=Decimal("1200000"),
        market_cap=Decimal("3500000000000.00000000"),
        market_data={"volatility": "moderate"},
    )


def _assert_user_filter_present(filter_args: tuple[object, ...], user_id: UUID) -> None:
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == user_id
        for arg in filter_args
    )


def test_create_snapshot() -> None:
    db = Mock()
    repository = MarketSnapshotRepository(db)

    created = repository.create(
        user_id=USER_A,
        source="MANUAL_CAPTURE",
        asset_symbol="AAPL",
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        asset_price=Decimal("195.25000000"),
        price_timestamp=datetime.now(timezone.utc),
        volume=Decimal("1200000"),
        market_cap=Decimal("3500000000000.00000000"),
        market_data={"volatility": "moderate"},
    )

    assert isinstance(created, MarketSnapshot)
    assert created.user_id == USER_A
    assert created.asset_symbol == "AAPL"
    db.add.assert_called_once_with(created)
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(created)


def test_get_by_id_retrieves_user_scoped_snapshot() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_snapshot()

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    result = repository.get_by_id(USER_A, SNAPSHOT_ID)

    assert result is not None
    assert result.user_id == USER_A

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)
    assert any(
        getattr(arg.left, "name", "") == "id" and arg.right.value == SNAPSHOT_ID
        for arg in filter_args
    )


def test_get_by_id_returns_none_when_missing() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    assert repository.get_by_id(USER_A, SNAPSHOT_ID) is None


def test_list_for_user_scopes_results_to_user() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [_build_snapshot()]

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    results = repository.list_for_user(USER_A)

    assert len(results) == 1
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_list_for_user_supports_asset_symbol_filter() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    repository.list_for_user(USER_A, asset_symbol="AAPL")

    filter_calls = query.filter.call_args_list
    assert len(filter_calls) == 2

    _assert_user_filter_present(filter_calls[0].args, USER_A)
    assert any(
        getattr(arg.left, "name", "") == "asset_symbol" and arg.right.value == "AAPL"
        for arg in filter_calls[1].args
    )


def test_list_for_user_orders_by_captured_at_desc() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [_build_snapshot()]

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    repository.list_for_user(USER_A)

    order_arg = query.order_by.call_args.args[0]
    assert getattr(getattr(order_arg, "element", None), "name", "") == "captured_at"


def test_list_for_user_supports_captured_at_range_filters() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)

    repository = MarketSnapshotRepository(db)
    repository.list_for_user(USER_A, captured_at_from=start, captured_at_to=end)

    filter_calls = query.filter.call_args_list
    assert len(filter_calls) == 3

    _assert_user_filter_present(filter_calls[0].args, USER_A)
    assert any(
        getattr(arg.left, "name", "") == "captured_at" and arg.right.value == start
        for arg in filter_calls[1].args
    )
    assert any(
        getattr(arg.left, "name", "") == "captured_at" and arg.right.value == end
        for arg in filter_calls[2].args
    )


def test_cannot_access_another_users_snapshot() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = MarketSnapshotRepository(db)
    result = repository.get_by_id(USER_B, SNAPSHOT_ID)

    assert result is None
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_B)


def test_repository_has_no_update_operation() -> None:
    repository = MarketSnapshotRepository(Mock())
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "update_lifecycle")
