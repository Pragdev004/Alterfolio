from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import RecommendationStatus
from app.models.recommendation import Recommendation
from app.repositories.recommendation_repository import RecommendationRepository


class InvalidRecommendationLifecycleTransitionError(ValueError):
    """Raised when a recommendation status transition is not allowed."""


class RecommendationLifecycleStateMachine:
    VALID_TRANSITIONS: dict[RecommendationStatus, set[RecommendationStatus]] = {
        RecommendationStatus.GENERATED: {
            RecommendationStatus.DISPLAYED,
        },
        RecommendationStatus.DISPLAYED: {
            RecommendationStatus.ACCEPTED,
            RecommendationStatus.IGNORED,
            RecommendationStatus.EXPIRED,
        },
        RecommendationStatus.ACCEPTED: {
            RecommendationStatus.EXECUTED,
            RecommendationStatus.EXPIRED,
        },
        RecommendationStatus.EXECUTED: {
            RecommendationStatus.EVALUATED,
        },
        RecommendationStatus.EVALUATED: {
            RecommendationStatus.ARCHIVED,
        },
        RecommendationStatus.IGNORED: {
            RecommendationStatus.ARCHIVED,
        },
        RecommendationStatus.EXPIRED: {
            RecommendationStatus.ARCHIVED,
        },
        RecommendationStatus.ARCHIVED: set(),
    }

    @classmethod
    def validate_transition(
        cls,
        current_status: RecommendationStatus,
        target_status: RecommendationStatus,
    ) -> None:
        allowed = cls.VALID_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise InvalidRecommendationLifecycleTransitionError(
                f"Invalid recommendation lifecycle transition: {current_status.value} -> {target_status.value}"
            )


class RecommendationLifecycleService:
    def __init__(
        self,
        db: Session,
        recommendation_repository: RecommendationRepository,
    ) -> None:
        self.db = db
        self.recommendation_repository = recommendation_repository

    def transition_status(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
        target_status: RecommendationStatus,
    ) -> Recommendation | None:
        recommendation = self.recommendation_repository.get_by_id(user_id, recommendation_id)
        if recommendation is None:
            return None

        RecommendationLifecycleStateMachine.validate_transition(
            recommendation.status,
            target_status,
        )

        try:
            updated = self.recommendation_repository.update_lifecycle(
                user_id=user_id,
                recommendation_id=recommendation_id,
                status=target_status,
            )
            if updated is None:
                return None

            self.db.commit()
            return updated
        except Exception:
            self.db.rollback()
            raise
