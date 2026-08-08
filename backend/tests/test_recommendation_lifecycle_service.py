from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import RecommendationStatus, RecommendationType
from app.models.recommendation import Recommendation
from app.services.recommendation_lifecycle_service import (
    InvalidRecommendationLifecycleTransitionError,
    RecommendationLifecycleService,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")


def _build_recommendation(status: RecommendationStatus) -> Recommendation:
    return Recommendation(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        status=status,
        recommendation_type=RecommendationType.BUY,
        asset_symbol="AAPL",
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.85000000"),
        risk_score=Decimal("0.30000000"),
        reasoning_text="Momentum and earnings quality.",
        reasoning_json={"signals": ["momentum"]},
        market_snapshot={"index_trend": "up"},
        market_snapshot_id=None,
        portfolio_snapshot_id=None,
        expires_at=None,
        evaluated_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _build_service() -> tuple[RecommendationLifecycleService, Mock, Mock]:
    db = Mock()
    repository = Mock()
    service = RecommendationLifecycleService(
        db=db,
        recommendation_repository=repository,
    )
    return service, db, repository


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (RecommendationStatus.GENERATED, RecommendationStatus.DISPLAYED),
        (RecommendationStatus.DISPLAYED, RecommendationStatus.ACCEPTED),
        (RecommendationStatus.DISPLAYED, RecommendationStatus.IGNORED),
        (RecommendationStatus.DISPLAYED, RecommendationStatus.EXPIRED),
        (RecommendationStatus.ACCEPTED, RecommendationStatus.EXECUTED),
        (RecommendationStatus.ACCEPTED, RecommendationStatus.EXPIRED),
        (RecommendationStatus.EXECUTED, RecommendationStatus.EVALUATED),
        (RecommendationStatus.EVALUATED, RecommendationStatus.ARCHIVED),
        (RecommendationStatus.IGNORED, RecommendationStatus.ARCHIVED),
        (RecommendationStatus.EXPIRED, RecommendationStatus.ARCHIVED),
    ],
)
def test_transition_status_allows_every_valid_transition(
    current_status: RecommendationStatus,
    target_status: RecommendationStatus,
) -> None:
    service, db, repository = _build_service()

    repository.get_by_id.return_value = _build_recommendation(current_status)
    updated = _build_recommendation(target_status)
    repository.update_lifecycle.return_value = updated

    result = service.transition_status(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        target_status=target_status,
    )

    assert result is updated
    repository.get_by_id.assert_called_once_with(USER_A, RECOMMENDATION_ID)
    repository.update_lifecycle.assert_called_once_with(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        status=target_status,
    )
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (RecommendationStatus.GENERATED, RecommendationStatus.ACCEPTED),
        (RecommendationStatus.GENERATED, RecommendationStatus.EXECUTED),
        (RecommendationStatus.GENERATED, RecommendationStatus.EVALUATED),
        (RecommendationStatus.DISPLAYED, RecommendationStatus.EXECUTED),
        (RecommendationStatus.DISPLAYED, RecommendationStatus.ARCHIVED),
        (RecommendationStatus.ACCEPTED, RecommendationStatus.EVALUATED),
        (RecommendationStatus.IGNORED, RecommendationStatus.ACCEPTED),
        (RecommendationStatus.EXPIRED, RecommendationStatus.ACCEPTED),
        (RecommendationStatus.EVALUATED, RecommendationStatus.GENERATED),
    ],
)
def test_transition_status_rejects_invalid_transitions_and_keeps_status_unchanged(
    current_status: RecommendationStatus,
    target_status: RecommendationStatus,
) -> None:
    service, db, repository = _build_service()

    recommendation = _build_recommendation(current_status)
    repository.get_by_id.return_value = recommendation

    with pytest.raises(InvalidRecommendationLifecycleTransitionError):
        service.transition_status(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            target_status=target_status,
        )

    assert recommendation.status == current_status
    repository.update_lifecycle.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_transition_status_rejects_any_transition_from_archived() -> None:
    service, db, repository = _build_service()

    recommendation = _build_recommendation(RecommendationStatus.ARCHIVED)
    repository.get_by_id.return_value = recommendation

    with pytest.raises(InvalidRecommendationLifecycleTransitionError):
        service.transition_status(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            target_status=RecommendationStatus.DISPLAYED,
        )

    assert recommendation.status == RecommendationStatus.ARCHIVED
    repository.update_lifecycle.assert_not_called()
    db.commit.assert_not_called()


def test_transition_status_returns_none_when_recommendation_not_found() -> None:
    service, db, repository = _build_service()

    repository.get_by_id.return_value = None

    result = service.transition_status(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        target_status=RecommendationStatus.DISPLAYED,
    )

    assert result is None
    repository.update_lifecycle.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_transition_status_preserves_user_isolation() -> None:
    service, _, repository = _build_service()

    repository.get_by_id.return_value = None

    service.transition_status(
        user_id=USER_B,
        recommendation_id=RECOMMENDATION_ID,
        target_status=RecommendationStatus.DISPLAYED,
    )

    repository.get_by_id.assert_called_once_with(USER_B, RECOMMENDATION_ID)
