from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.baseline_decision import BaselineDecision
from app.models.enums import BaselineAction, Currency, RecommendationStatus, RecommendationType
from app.models.market_snapshot import MarketSnapshot
from app.models.neutral_baseline_strategy import MAINTAIN_CURRENT_ALLOCATION_STRATEGY
from app.models.recommendation import Recommendation
from app.repositories.baseline_decision_repository import (
    BaselineDecisionMissingMarketContextError,
    BaselineDecisionRecommendationNotFoundError,
    BaselineDecisionRepository,
    DuplicateBaselineDecisionError,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT_ID = UUID("44444444-4444-4444-8444-444444444444")
BASELINE_DECISION_ID = UUID("55555555-5555-4555-8555-555555555555")


def _build_market_snapshot(*, user_id: UUID = USER_A) -> MarketSnapshot:
    return MarketSnapshot(
        id=SNAPSHOT_ID,
        user_id=user_id,
        captured_at=datetime.now(timezone.utc),
        source="MANUAL_CAPTURE",
        asset_symbol="MSFT",
        exchange=None,
        asset_type=None,
        currency=Currency.INR,
        asset_price=Decimal("395.12500000"),
        price_timestamp=datetime.now(timezone.utc),
        volume=None,
        market_cap=None,
        market_data={"index_trend": "up"},
    )


def _build_recommendation(*, user_id: UUID = USER_A, with_market_context: bool = True) -> Recommendation:
    recommendation = Recommendation(
        id=RECOMMENDATION_ID,
        user_id=user_id,
        status=RecommendationStatus.GENERATED,
        recommendation_type=RecommendationType.INCREASE,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10000000"),
        expected_holding_period_days=90,
        confidence_score=Decimal("0.91000000"),
        risk_score=Decimal("0.24000000"),
        reasoning_text="Increase allocation due to stable quality and momentum.",
        reasoning_json={"signals": ["quality", "momentum"]},
        market_snapshot={"index_trend": "up"},
        market_snapshot_id=SNAPSHOT_ID if with_market_context else None,
        portfolio_snapshot_id=None,
        expires_at=None,
        evaluated_at=None,
        created_at=datetime.now(timezone.utc),
    )

    recommendation.context_market_snapshot = _build_market_snapshot(user_id=user_id) if with_market_context else None
    return recommendation


def _build_baseline_decision(*, user_id: UUID = USER_A) -> BaselineDecision:
    return BaselineDecision(
        id=BASELINE_DECISION_ID,
        user_id=user_id,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.05000000"),
        created_at=datetime.now(timezone.utc),
    )


def _assert_user_filter_present(filter_args: tuple[object, ...], user_id: UUID) -> None:
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == user_id
        for arg in filter_args
    )


def test_create_valid_neutral_baseline_decision() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.05000000"),
    )

    assert isinstance(created, BaselineDecision)
    assert created.user_id == USER_A
    assert created.recommendation_id == RECOMMENDATION_ID
    db.add.assert_called_once_with(created)


def test_strategy_key_is_persisted() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.05000000"),
    )

    assert created.strategy_key == MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key


def test_strategy_version_is_persisted() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.05000000"),
    )

    assert created.strategy_version == MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version


def test_baseline_action_is_maintain() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.05000000"),
    )

    assert created.baseline_action == BaselineAction.MAINTAIN


def test_baseline_allocation_preserves_decimal_precision() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)
    precise_value = Decimal("0.12345678")

    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=precise_value,
    )

    assert created.baseline_allocation == precise_value


def test_get_by_id_retrieves_user_scoped_baseline_decision() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_baseline_decision()

    db = Mock()
    db.query.return_value = query

    repository = BaselineDecisionRepository(db)
    result = repository.get_by_id(USER_A, BASELINE_DECISION_ID)

    assert result is not None
    assert result.user_id == USER_A

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_get_for_recommendation_retrieves_user_scoped_baseline_decision() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_baseline_decision()

    db = Mock()
    db.query.return_value = query

    repository = BaselineDecisionRepository(db)
    result = repository.get_for_recommendation(USER_A, RECOMMENDATION_ID)

    assert result is not None
    assert result.recommendation_id == RECOMMENDATION_ID

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_user_isolation_enforced_in_get_by_id() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = None

    db = Mock()
    db.query.return_value = query

    repository = BaselineDecisionRepository(db)
    result = repository.get_by_id(USER_B, BASELINE_DECISION_ID)

    assert result is None
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_B)


def test_create_rejects_missing_recommendation() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = None

    db = Mock()
    db.query.return_value = recommendation_query

    repository = BaselineDecisionRepository(db)

    with pytest.raises(BaselineDecisionRecommendationNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
            strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
            baseline_action=BaselineAction.MAINTAIN,
            baseline_allocation=Decimal("0.05000000"),
        )


def test_create_rejects_cross_user_recommendation() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = None

    db = Mock()
    db.query.return_value = recommendation_query

    repository = BaselineDecisionRepository(db)

    with pytest.raises(BaselineDecisionRecommendationNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
            strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
            baseline_action=BaselineAction.MAINTAIN,
            baseline_allocation=Decimal("0.05000000"),
        )

    filter_args = recommendation_query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_create_rejects_duplicate_for_same_user_recommendation() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = _build_baseline_decision()

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = BaselineDecisionRepository(db)

    with pytest.raises(DuplicateBaselineDecisionError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
            strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
            baseline_action=BaselineAction.MAINTAIN,
            baseline_allocation=Decimal("0.05000000"),
        )


def test_create_rejects_missing_required_market_context() -> None:
    recommendation_query = Mock()
    recommendation_query.options.return_value = recommendation_query
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation(with_market_context=False)

    db = Mock()
    db.query.return_value = recommendation_query

    repository = BaselineDecisionRepository(db)

    with pytest.raises(BaselineDecisionMissingMarketContextError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
            strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
            baseline_action=BaselineAction.MAINTAIN,
            baseline_allocation=Decimal("0.05000000"),
        )


def test_repository_has_no_update_method() -> None:
    repository = BaselineDecisionRepository(Mock())

    assert not hasattr(repository, "update")
    assert not hasattr(repository, "update_lifecycle")


def test_list_for_user_is_user_scoped() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [_build_baseline_decision()]

    db = Mock()
    db.query.return_value = query

    repository = BaselineDecisionRepository(db)
    results = repository.list_for_user(USER_A)

    assert len(results) == 1
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)
