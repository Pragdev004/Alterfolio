from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.enums import RecommendationStatus, RecommendationType
from app.models.market_snapshot import MarketSnapshot
from app.models.recommendation import Recommendation


class RecommendationMarketSnapshotMismatchError(ValueError):
    """Raised when a recommendation references a missing or cross-user market snapshot."""


class InvalidSuggestedAllocationError(ValueError):
    """Raised when suggested_allocation is outside [0, 1] fraction bounds."""


class RecommendationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: UUID,
        recommendation_type: RecommendationType,
        asset_symbol: str,
        suggested_allocation: Decimal,
        expected_holding_period_days: int,
        confidence_score: Decimal,
        risk_score: Decimal,
        reasoning_text: str,
        reasoning_json: dict,
        market_snapshot: dict,
        market_snapshot_id: UUID | None = None,
        portfolio_snapshot_id: UUID | None = None,
        expires_at: datetime | None = None,
        status: RecommendationStatus = RecommendationStatus.GENERATED,
    ) -> Recommendation:
        self._validate_suggested_allocation(suggested_allocation)

        if market_snapshot_id is not None:
            snapshot = (
                self.db.query(MarketSnapshot)
                .filter(
                    MarketSnapshot.user_id == user_id,
                    MarketSnapshot.id == market_snapshot_id,
                )
                .first()
            )
            if snapshot is None:
                raise RecommendationMarketSnapshotMismatchError(
                    "market_snapshot_id does not exist for the user"
                )

        recommendation = Recommendation(
            user_id=user_id,
            recommendation_type=recommendation_type,
            asset_symbol=asset_symbol,
            suggested_allocation=suggested_allocation,
            expected_holding_period_days=expected_holding_period_days,
            confidence_score=confidence_score,
            risk_score=risk_score,
            reasoning_text=reasoning_text,
            reasoning_json=reasoning_json,
            market_snapshot=market_snapshot,
            market_snapshot_id=market_snapshot_id,
            portfolio_snapshot_id=portfolio_snapshot_id,
            expires_at=expires_at,
            status=status,
        )

        self.db.add(recommendation)
        self.db.flush()
        self.db.refresh(recommendation)

        return recommendation

    @staticmethod
    def _validate_suggested_allocation(suggested_allocation: Decimal) -> None:
        # suggested_allocation semantics:
        # final target portfolio weight for the recommended asset,
        # represented as a Decimal fraction of total portfolio value.
        if not isinstance(suggested_allocation, Decimal):
            raise InvalidSuggestedAllocationError(
                "suggested_allocation must be provided as Decimal"
            )

        if suggested_allocation < Decimal("0") or suggested_allocation > Decimal("1"):
            raise InvalidSuggestedAllocationError(
                "suggested_allocation must be a Decimal fraction between 0 and 1 inclusive"
            )

    def get_by_id(
        self,
        user_id: UUID,
        recommendation_id: UUID,
        *,
        include_market_snapshot: bool = False,
    ) -> Recommendation | None:
        query = self.db.query(Recommendation)

        if include_market_snapshot:
            query = query.options(joinedload(Recommendation.context_market_snapshot))

        return (
            query.filter(
                Recommendation.user_id == user_id,
                Recommendation.id == recommendation_id,
            ).first()
        )

    def list_for_user(
        self,
        user_id: UUID,
        *,
        status: RecommendationStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Recommendation]:
        query = self.db.query(Recommendation).filter(Recommendation.user_id == user_id)

        if status is not None:
            query = query.filter(Recommendation.status == status)

        query = query.order_by(Recommendation.created_at.desc())

        if offset:
            query = query.offset(offset)

        if limit is not None:
            query = query.limit(limit)

        return query.all()

    def update_lifecycle(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
        status: RecommendationStatus | None = None,
        expires_at: datetime | None = None,
        evaluated_at: datetime | None = None,
    ) -> Recommendation | None:
        recommendation = self.get_by_id(user_id, recommendation_id)

        if recommendation is None:
            return None

        if status is not None:
            recommendation.status = status

        if expires_at is not None:
            recommendation.expires_at = expires_at

        if evaluated_at is not None:
            recommendation.evaluated_at = evaluated_at

        self.db.flush()
        self.db.refresh(recommendation)

        return recommendation
