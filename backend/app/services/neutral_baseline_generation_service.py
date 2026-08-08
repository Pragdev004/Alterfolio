from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.baseline_decision import BaselineDecision
from app.models.enums import BaselineAction
from app.models.neutral_baseline_strategy import MAINTAIN_CURRENT_ALLOCATION_STRATEGY
from app.repositories.baseline_decision_repository import BaselineDecisionRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.services.portfolio_allocation_as_of_service import (
    InvalidHoldingQuantityError,
    MissingHistoricalPriceError,
    NonPositivePortfolioValueError,
    PortfolioAllocationAsOfService,
    UnsupportedMultiCurrencyValuationError,
)


class BaselineGenerationRecommendationNotFoundError(ValueError):
    """Raised when the recommendation does not exist for the provided user."""


class BaselineGenerationMissingMarketContextError(ValueError):
    """Raised when recommendation market context is unavailable for baseline generation."""


class BaselineGenerationHistoricalAllocationUnavailableError(ValueError):
    """Raised when historical portfolio allocation cannot be reconstructed."""


class BaselineGenerationAssetAllocationNotFoundError(ValueError):
    """Raised when recommended asset is absent in historical allocation at recommendation time."""


class NeutralBaselineGenerationService:
    def __init__(
        self,
        db: Session,
        recommendation_repository: RecommendationRepository,
        baseline_decision_repository: BaselineDecisionRepository,
        portfolio_allocation_as_of_service: PortfolioAllocationAsOfService,
    ) -> None:
        self.db = db
        self.recommendation_repository = recommendation_repository
        self.baseline_decision_repository = baseline_decision_repository
        self.portfolio_allocation_as_of_service = portfolio_allocation_as_of_service

    def generate_for_recommendation(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
    ) -> BaselineDecision:
        recommendation = self.recommendation_repository.get_by_id(
            user_id,
            recommendation_id,
            include_market_snapshot=True,
        )
        if recommendation is None:
            raise BaselineGenerationRecommendationNotFoundError(
                "recommendation_id does not exist for the user"
            )

        if recommendation.market_snapshot_id is None or recommendation.context_market_snapshot is None:
            raise BaselineGenerationMissingMarketContextError(
                "recommendation does not have required market context"
            )

        try:
            allocation_as_of = self.portfolio_allocation_as_of_service.get_portfolio_allocation_as_of(
                user_id=user_id,
                as_of=recommendation.created_at,
            )
        except (
            MissingHistoricalPriceError,
            UnsupportedMultiCurrencyValuationError,
            InvalidHoldingQuantityError,
            NonPositivePortfolioValueError,
        ) as exc:
            raise BaselineGenerationHistoricalAllocationUnavailableError(
                "historical allocation is unavailable at recommendation.created_at"
            ) from exc

        allocation_for_asset = next(
            (
                allocation
                for allocation in allocation_as_of.allocations
                if allocation.asset_symbol == recommendation.asset_symbol
            ),
            None,
        )

        if allocation_for_asset is None:
            raise BaselineGenerationAssetAllocationNotFoundError(
                "recommended asset has no historical allocation at recommendation.created_at"
            )

        try:
            decision = self.baseline_decision_repository.create(
                user_id=user_id,
                recommendation_id=recommendation_id,
                strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
                strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
                baseline_action=BaselineAction.MAINTAIN,
                baseline_allocation=allocation_for_asset.allocation,
            )
            self.db.commit()
            return decision
        except Exception:
            self.db.rollback()
            raise
