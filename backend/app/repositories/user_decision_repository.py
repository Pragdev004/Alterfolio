from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import UserDecisionType
from app.models.recommendation import Recommendation
from app.models.trade import Trade
from app.models.user_decision import UserDecision


class UserDecisionRecommendationNotFoundError(ValueError):
    """Raised when a user-scoped recommendation does not exist for the decision."""


class UserDecisionTradeNotFoundError(ValueError):
    """Raised when a user-scoped trade does not exist for the decision."""


class DuplicateUserDecisionError(ValueError):
    """Raised when a decision already exists for a user recommendation pair."""


class InvalidModifiedAllocationError(ValueError):
    """Raised when modified_allocation is outside [0, 1] fraction bounds."""


class UserDecisionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
        decision_type: UserDecisionType,
        trade_id: UUID | None = None,
        decided_at: datetime | None = None,
        modified_allocation: Decimal | None = None,
        decision_note: str | None = None,
    ) -> UserDecision:
        self._validate_modified_allocation(modified_allocation)

        recommendation = (
            self.db.query(Recommendation)
            .filter(
                Recommendation.user_id == user_id,
                Recommendation.id == recommendation_id,
            )
            .first()
        )
        if recommendation is None:
            raise UserDecisionRecommendationNotFoundError(
                "recommendation_id does not exist for the user"
            )

        if trade_id is not None:
            trade = (
                self.db.query(Trade)
                .filter(
                    Trade.user_id == user_id,
                    Trade.id == trade_id,
                )
                .first()
            )
            if trade is None:
                raise UserDecisionTradeNotFoundError(
                    "trade_id does not exist for the user"
                )

        existing = (
            self.db.query(UserDecision)
            .filter(
                UserDecision.user_id == user_id,
                UserDecision.recommendation_id == recommendation_id,
            )
            .first()
        )
        if existing is not None:
            raise DuplicateUserDecisionError(
                "decision already exists for user and recommendation"
            )

        decision = UserDecision(
            user_id=user_id,
            recommendation_id=recommendation_id,
            trade_id=trade_id,
            decision_type=decision_type,
            modified_allocation=modified_allocation,
            decision_note=decision_note,
        )

        if decided_at is not None:
            decision.decided_at = decided_at

        self.db.add(decision)
        self.db.flush()
        self.db.refresh(decision)

        return decision

    @staticmethod
    def _validate_modified_allocation(modified_allocation: Decimal | None) -> None:
        # modified_allocation semantics (when present):
        # final target portfolio weight for the recommended asset,
        # represented as a Decimal fraction of total portfolio value.
        if modified_allocation is None:
            return

        if not isinstance(modified_allocation, Decimal):
            raise InvalidModifiedAllocationError(
                "modified_allocation must be provided as Decimal"
            )

        if modified_allocation < Decimal("0") or modified_allocation > Decimal("1"):
            raise InvalidModifiedAllocationError(
                "modified_allocation must be a Decimal fraction between 0 and 1 inclusive"
            )

    def get_by_id(self, user_id: UUID, decision_id: UUID) -> UserDecision | None:
        return (
            self.db.query(UserDecision)
            .filter(
                UserDecision.user_id == user_id,
                UserDecision.id == decision_id,
            )
            .first()
        )

    def get_for_recommendation(self, user_id: UUID, recommendation_id: UUID) -> UserDecision | None:
        return (
            self.db.query(UserDecision)
            .filter(
                UserDecision.user_id == user_id,
                UserDecision.recommendation_id == recommendation_id,
            )
            .first()
        )

    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserDecision]:
        query = self.db.query(UserDecision).filter(UserDecision.user_id == user_id)
        query = query.order_by(UserDecision.decided_at.desc())

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()
