from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import Currency, RecommendationStatus, RecommendationType
from app.models.market_snapshot import MarketSnapshot
from app.models.recommendation import Recommendation
from app.repositories.recommendation_repository import (
    RecommendationMarketSnapshotMismatchError,
    RecommendationRepository,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT_ID = UUID("44444444-4444-4444-8444-444444444444")


def _build_recommendation(
    *,
    user_id: UUID = USER_A,
    status: RecommendationStatus = RecommendationStatus.GENERATED,
) -> Recommendation:
    return Recommendation(
        id=RECOMMENDATION_ID,
        user_id=user_id,
        status=status,
        recommendation_type=RecommendationType.BUY,
        asset_symbol="AAPL",
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.85000000"),
        risk_score=Decimal("0.30000000"),
        reasoning_text="Momentum and earnings quality.",
        reasoning_json={"signals": ["momentum", "earnings"]},
        market_snapshot={"index_trend": "up"},
        market_snapshot_id=None,
        portfolio_snapshot_id=None,
        expires_at=None,
        evaluated_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _assert_user_filter_present(filter_args: tuple[object, ...], user_id: UUID) -> None:
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == user_id
        for arg in filter_args
    )


def _build_market_snapshot(*, user_id: UUID = USER_A) -> MarketSnapshot:
    return MarketSnapshot(
        id=SNAPSHOT_ID,
        user_id=user_id,
        captured_at=datetime.now(timezone.utc),
        source="MANUAL_CAPTURE",
        asset_symbol="AAPL",
        exchange=None,
        asset_type=None,
        currency=Currency.INR,
        asset_price=Decimal("195.25000000"),
        price_timestamp=datetime.now(timezone.utc),
        volume=None,
        market_cap=None,
        market_data={"volatility": "moderate"},
    )


def test_create_recommendation() -> None:
    db = Mock()
    repository = RecommendationRepository(db)

    created = repository.create(
        user_id=USER_A,
        recommendation_type=RecommendationType.BUY,
        asset_symbol="AAPL",
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.85000000"),
        risk_score=Decimal("0.30000000"),
        reasoning_text="Momentum and earnings quality.",
        reasoning_json={"signals": ["momentum", "earnings"]},
        market_snapshot={"index_trend": "up"},
    )

    assert isinstance(created, Recommendation)
    assert created.user_id == USER_A
    assert created.recommendation_type == RecommendationType.BUY
    assert created.status == RecommendationStatus.GENERATED
    assert created.market_snapshot_id is None
    db.add.assert_called_once_with(created)
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(created)


def test_create_recommendation_with_same_user_market_snapshot_succeeds() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_market_snapshot(user_id=USER_A)

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_type=RecommendationType.BUY,
        asset_symbol="AAPL",
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.85000000"),
        risk_score=Decimal("0.30000000"),
        reasoning_text="Momentum and earnings quality.",
        reasoning_json={"signals": ["momentum", "earnings"]},
        market_snapshot={"index_trend": "up"},
        market_snapshot_id=SNAPSHOT_ID,
    )

    assert created.market_snapshot_id == SNAPSHOT_ID
    db.add.assert_called_once_with(created)


def test_create_recommendation_rejects_missing_market_snapshot() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    with pytest.raises(RecommendationMarketSnapshotMismatchError):
        repository.create(
            user_id=USER_A,
            recommendation_type=RecommendationType.BUY,
            asset_symbol="AAPL",
            suggested_allocation=Decimal("0.25000000"),
            expected_holding_period_days=30,
            confidence_score=Decimal("0.85000000"),
            risk_score=Decimal("0.30000000"),
            reasoning_text="Momentum and earnings quality.",
            reasoning_json={"signals": ["momentum", "earnings"]},
            market_snapshot={"index_trend": "up"},
            market_snapshot_id=SNAPSHOT_ID,
        )

    snapshot_filter_args = query.filter.call_args.args
    _assert_user_filter_present(snapshot_filter_args, USER_A)
    db.add.assert_not_called()


def test_create_recommendation_rejects_other_users_market_snapshot() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    with pytest.raises(RecommendationMarketSnapshotMismatchError):
        repository.create(
            user_id=USER_A,
            recommendation_type=RecommendationType.BUY,
            asset_symbol="AAPL",
            suggested_allocation=Decimal("0.25000000"),
            expected_holding_period_days=30,
            confidence_score=Decimal("0.85000000"),
            risk_score=Decimal("0.30000000"),
            reasoning_text="Momentum and earnings quality.",
            reasoning_json={"signals": ["momentum", "earnings"]},
            market_snapshot={"index_trend": "up"},
            market_snapshot_id=SNAPSHOT_ID,
        )

    snapshot_filter_args = query.filter.call_args.args
    _assert_user_filter_present(snapshot_filter_args, USER_A)
    db.add.assert_not_called()


def test_get_by_id_retrieves_user_scoped_recommendation() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_recommendation()

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    result = repository.get_by_id(USER_A, RECOMMENDATION_ID)

    assert result is not None
    assert result.user_id == USER_A

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)
    assert any(
        getattr(arg.left, "name", "") == "id" and arg.right.value == RECOMMENDATION_ID
        for arg in filter_args
    )


def test_get_by_id_can_include_associated_market_snapshot() -> None:
    query = Mock()
    query.options.return_value = query
    query.filter.return_value = query
    query.first.return_value = _build_recommendation()

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    result = repository.get_by_id(USER_A, RECOMMENDATION_ID, include_market_snapshot=True)

    assert result is not None
    query.options.assert_called_once()


def test_get_by_id_returns_none_when_missing() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    assert repository.get_by_id(USER_A, RECOMMENDATION_ID) is None


def test_user_isolation_enforced_in_get_by_id_query() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    repository.get_by_id(USER_A, RECOMMENDATION_ID)

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_list_for_user_scopes_to_user_and_orders_by_created_at_desc() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [_build_recommendation()]

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    results = repository.list_for_user(USER_A)

    assert len(results) == 1
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)

    order_arg = query.order_by.call_args.args[0]
    assert getattr(getattr(order_arg, "element", None), "name", "") == "created_at"


def test_list_for_user_supports_status_filter() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)
    repository.list_for_user(USER_A, status=RecommendationStatus.ACCEPTED)

    filter_calls = query.filter.call_args_list
    assert len(filter_calls) == 2

    first_filter_args = filter_calls[0].args
    second_filter_args = filter_calls[1].args

    _assert_user_filter_present(first_filter_args, USER_A)
    assert any(
        getattr(arg.left, "name", "") == "status" and arg.right.value == RecommendationStatus.ACCEPTED
        for arg in second_filter_args
    )


def test_update_lifecycle_fields_for_user_scoped_recommendation() -> None:
    existing = _build_recommendation()

    query = Mock()
    query.filter.return_value = query
    query.first.return_value = existing

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    updated = repository.update_lifecycle(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        status=RecommendationStatus.EVALUATED,
        evaluated_at=datetime.now(timezone.utc),
    )

    assert updated is existing
    assert updated.status == RecommendationStatus.EVALUATED
    assert updated.evaluated_at is not None
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(existing)


def test_update_lifecycle_returns_none_when_missing() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    updated = repository.update_lifecycle(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        status=RecommendationStatus.ARCHIVED,
    )

    assert updated is None
    db.flush.assert_not_called()
    db.refresh.assert_not_called()


def test_cannot_access_another_users_recommendation() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = RecommendationRepository(db)

    result = repository.get_by_id(USER_B, RECOMMENDATION_ID)

    assert result is None
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_B)
