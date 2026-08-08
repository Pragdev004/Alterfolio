from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import Mock

from app.models.enums import TradeStatus
from app.repositories.trade_repository import TradeRepository


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
AS_OF = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)


def _assert_user_filter_present(filter_args: tuple[object, ...], user_id: UUID) -> None:
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == user_id
        for arg in filter_args
    )


def test_list_executed_up_to_applies_user_status_and_as_of_filters() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = TradeRepository(db)
    repository.list_executed_up_to(user_id=USER_ID, as_of=AS_OF)

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_ID)

    assert any(
        getattr(arg.left, "name", "") == "status" and arg.right.value == TradeStatus.EXECUTED
        for arg in filter_args
    )
    assert any(
        getattr(arg.left, "name", "") == "trade_timestamp" and arg.right.value == AS_OF
        for arg in filter_args
    )


def test_list_executed_up_to_orders_deterministically_by_timestamp_then_id() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = TradeRepository(db)
    repository.list_executed_up_to(user_id=USER_ID, as_of=AS_OF)

    order_args = query.order_by.call_args.args
    assert len(order_args) == 2

    timestamp_order, id_order = order_args

    assert getattr(getattr(timestamp_order, "element", None), "name", "") == "trade_timestamp"
    assert getattr(getattr(id_order, "element", None), "name", "") == "id"


def test_list_executed_up_to_preserves_user_isolation() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = TradeRepository(db)
    repository.list_executed_up_to(user_id=USER_ID, as_of=AS_OF)

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_ID)
