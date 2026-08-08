from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.baseline_decision import BaselineDecision
from app.models.enums import BaselineAction
from app.models.recommendation import Recommendation


class BaselineDecisionRecommendationNotFoundError(ValueError):
    """Raised when a user-scoped recommendation does not exist for baseline creation."""


class BaselineDecisionMissingMarketContextError(ValueError):
    """Raised when recommendation context market snapshot is unavailable."""


class DuplicateBaselineDecisionError(ValueError):
    """Raised when a baseline decision already exists for the user recommendation pair."""


class BaselineDecisionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
        strategy_key: str,
        strategy_version: str,
        baseline_action: BaselineAction,
        baseline_allocation: Decimal,
        created_at: datetime | None = None,
    ) -> BaselineDecision:
        recommendation = (
            self.db.query(Recommendation)
            .options(joinedload(Recommendation.context_market_snapshot))
            .filter(
                Recommendation.user_id == user_id,
                Recommendation.id == recommendation_id,
            )
            .first()
        )
        if recommendation is None:
            raise BaselineDecisionRecommendationNotFoundError(
                "recommendation_id does not exist for the user"
            )

        if recommendation.market_snapshot_id is None or recommendation.context_market_snapshot is None:
            raise BaselineDecisionMissingMarketContextError(
                "recommendation does not have required market context"
            )

        existing = (
            self.db.query(BaselineDecision)
            .filter(
                BaselineDecision.user_id == user_id,
                BaselineDecision.recommendation_id == recommendation_id,
            )
            .first()
        )
        if existing is not None:
            raise DuplicateBaselineDecisionError(
                "baseline decision already exists for user and recommendation"
            )

        decision = BaselineDecision(
            user_id=user_id,
            recommendation_id=recommendation_id,
            strategy_key=strategy_key,
            strategy_version=strategy_version,
            baseline_action=baseline_action,
            baseline_allocation=baseline_allocation,
        )

        if created_at is not None:
            decision.created_at = created_at

        self.db.add(decision)
        self.db.flush()
        self.db.refresh(decision)

        return decision

    def get_by_id(self, user_id: UUID, baseline_decision_id: UUID) -> BaselineDecision | None:
        return (
            self.db.query(BaselineDecision)
            .filter(
                BaselineDecision.user_id == user_id,
                BaselineDecision.id == baseline_decision_id,
            )
            .first()
        )

    def get_for_recommendation(self, user_id: UUID, recommendation_id: UUID) -> BaselineDecision | None:
        return (
            self.db.query(BaselineDecision)
            .filter(
                BaselineDecision.user_id == user_id,
                BaselineDecision.recommendation_id == recommendation_id,
            )
            .first()
        )

    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BaselineDecision]:
        query = self.db.query(BaselineDecision).filter(BaselineDecision.user_id == user_id)
        query = query.order_by(BaselineDecision.created_at.desc())

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()
