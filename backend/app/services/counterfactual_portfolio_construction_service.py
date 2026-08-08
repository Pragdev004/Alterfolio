from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.models.enums import AssetType, Currency, Exchange
from app.repositories.recommendation_repository import RecommendationRepository
from app.services.portfolio_allocation_as_of_service import (
    InvalidHoldingQuantityError,
    MissingHistoricalPriceError,
    NonPositivePortfolioValueError,
    PortfolioAllocationAsOf,
    PortfolioAllocationAsOfService,
    PortfolioAllocationAssetAsOf,
    UnsupportedMultiCurrencyValuationError,
)


class CounterfactualRecommendationNotFoundError(ValueError):
    """Raised when recommendation_id does not exist for the provided user."""


class CounterfactualHistoricalAllocationUnavailableError(ValueError):
    """Raised when historical allocation cannot be reconstructed at recommendation time."""


class InvalidCounterfactualSuggestedAllocationError(ValueError):
    """Raised when target allocation is invalid for counterfactual construction."""


class CounterfactualRecommendedAssetAmbiguousError(ValueError):
    """Raised when historical allocation contains multiple entries for recommended symbol."""


class CounterfactualEmptyPortfolioError(ValueError):
    """Raised when counterfactual cannot be built from empty historical holdings context."""


class CounterfactualInsufficientNonRecommendedAllocationError(ValueError):
    """Raised when target < 1 but no non-recommended allocation exists to scale."""


class CounterfactualUnsupportedMultiCurrencyError(ValueError):
    """Raised when input allocation spans multiple currencies without FX support."""


@dataclass(frozen=True)
class CounterfactualPortfolioAsset:
    asset_symbol: str
    exchange: Exchange | None
    asset_type: AssetType | None
    currency: Currency
    original_allocation: Decimal
    counterfactual_allocation: Decimal


@dataclass(frozen=True)
class CounterfactualPortfolio:
    as_of: datetime
    total_allocation: Decimal
    assets: list[CounterfactualPortfolioAsset]


class CounterfactualPortfolioConstructionService:
    def __init__(
        self,
        recommendation_repository: RecommendationRepository,
        portfolio_allocation_as_of_service: PortfolioAllocationAsOfService,
    ) -> None:
        self.recommendation_repository = recommendation_repository
        self.portfolio_allocation_as_of_service = portfolio_allocation_as_of_service

    def construct_for_recommendation(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
    ) -> CounterfactualPortfolio:
        recommendation = self.recommendation_repository.get_by_id(
            user_id,
            recommendation_id,
        )
        if recommendation is None:
            raise CounterfactualRecommendationNotFoundError(
                "recommendation_id does not exist for the user"
            )

        try:
            historical_allocation = self.portfolio_allocation_as_of_service.get_portfolio_allocation_as_of(
                user_id=user_id,
                as_of=recommendation.created_at,
            )
        except (
            MissingHistoricalPriceError,
            UnsupportedMultiCurrencyValuationError,
            InvalidHoldingQuantityError,
            NonPositivePortfolioValueError,
        ) as exc:
            raise CounterfactualHistoricalAllocationUnavailableError(
                "historical allocation is unavailable at recommendation.created_at"
            ) from exc

        return self.construct_from_historical_allocation(
            historical_allocation=historical_allocation,
            recommended_asset_symbol=recommendation.asset_symbol,
            suggested_allocation=recommendation.suggested_allocation,
        )

    def construct_from_historical_allocation(
        self,
        *,
        historical_allocation: PortfolioAllocationAsOf,
        recommended_asset_symbol: str,
        suggested_allocation: Decimal,
    ) -> CounterfactualPortfolio:
        self._validate_suggested_allocation(suggested_allocation)

        ordered_original_assets = self._sorted_assets(historical_allocation.allocations)

        if not ordered_original_assets:
            if suggested_allocation == Decimal("0"):
                return CounterfactualPortfolio(
                    as_of=historical_allocation.as_of,
                    total_allocation=Decimal("0"),
                    assets=[],
                )

            raise CounterfactualEmptyPortfolioError(
                "cannot construct counterfactual allocation for target > 0 with empty historical portfolio"
            )

        currencies = {asset.currency for asset in ordered_original_assets}
        if len(currencies) > 1:
            raise CounterfactualUnsupportedMultiCurrencyError(
                "counterfactual allocation across multiple currencies requires FX conversion, which is unsupported"
            )

        recommended_matches = [
            asset
            for asset in ordered_original_assets
            if asset.asset_symbol == recommended_asset_symbol
        ]

        if len(recommended_matches) > 1:
            raise CounterfactualRecommendedAssetAmbiguousError(
                "recommended asset has multiple historical allocation entries"
            )

        recommended_original = recommended_matches[0] if recommended_matches else None
        non_recommended_assets = [
            asset
            for asset in ordered_original_assets
            if asset.asset_symbol != recommended_asset_symbol
        ]

        non_recommended_total = sum(
            (asset.allocation for asset in non_recommended_assets),
            Decimal("0"),
        )
        remaining_weight = Decimal("1") - suggested_allocation

        if remaining_weight > Decimal("0") and non_recommended_total == Decimal("0"):
            raise CounterfactualInsufficientNonRecommendedAllocationError(
                "target allocation is less than 1 but no non-recommended allocation exists"
            )

        counterfactual_non_recommended = self._scale_non_recommended_allocations(
            non_recommended_assets=non_recommended_assets,
            non_recommended_total=non_recommended_total,
            remaining_weight=remaining_weight,
        )

        recommended_currency = self._resolve_recommended_currency(
            historical_allocation=historical_allocation,
            recommended_original=recommended_original,
        )

        recommended_asset = CounterfactualPortfolioAsset(
            asset_symbol=recommended_asset_symbol,
            exchange=recommended_original.exchange if recommended_original is not None else None,
            asset_type=recommended_original.asset_type if recommended_original is not None else None,
            currency=recommended_currency,
            original_allocation=(
                recommended_original.allocation
                if recommended_original is not None
                else Decimal("0")
            ),
            counterfactual_allocation=suggested_allocation,
        )

        counterfactual_assets = self._sorted_counterfactual_assets(
            [*counterfactual_non_recommended, recommended_asset]
        )

        total_allocation = sum(
            (asset.counterfactual_allocation for asset in counterfactual_assets),
            Decimal("0"),
        )

        return CounterfactualPortfolio(
            as_of=historical_allocation.as_of,
            total_allocation=total_allocation,
            assets=counterfactual_assets,
        )

    @staticmethod
    def _validate_suggested_allocation(suggested_allocation: Decimal) -> None:
        if not isinstance(suggested_allocation, Decimal):
            raise InvalidCounterfactualSuggestedAllocationError(
                "suggested_allocation must be provided as Decimal"
            )

        if suggested_allocation < Decimal("0") or suggested_allocation > Decimal("1"):
            raise InvalidCounterfactualSuggestedAllocationError(
                "suggested_allocation must be a Decimal fraction between 0 and 1 inclusive"
            )

    def _scale_non_recommended_allocations(
        self,
        *,
        non_recommended_assets: list[PortfolioAllocationAssetAsOf],
        non_recommended_total: Decimal,
        remaining_weight: Decimal,
    ) -> list[CounterfactualPortfolioAsset]:
        if not non_recommended_assets:
            return []

        if remaining_weight == Decimal("0"):
            return [
                CounterfactualPortfolioAsset(
                    asset_symbol=asset.asset_symbol,
                    exchange=asset.exchange,
                    asset_type=asset.asset_type,
                    currency=asset.currency,
                    original_allocation=asset.allocation,
                    counterfactual_allocation=Decimal("0"),
                )
                for asset in non_recommended_assets
            ]

        scaled_assets: list[CounterfactualPortfolioAsset] = []
        allocated_so_far = Decimal("0")

        for index, asset in enumerate(non_recommended_assets):
            is_last = index == len(non_recommended_assets) - 1
            if is_last:
                counterfactual_allocation = remaining_weight - allocated_so_far
            else:
                counterfactual_allocation = (asset.allocation / non_recommended_total) * remaining_weight
                allocated_so_far += counterfactual_allocation

            scaled_assets.append(
                CounterfactualPortfolioAsset(
                    asset_symbol=asset.asset_symbol,
                    exchange=asset.exchange,
                    asset_type=asset.asset_type,
                    currency=asset.currency,
                    original_allocation=asset.allocation,
                    counterfactual_allocation=counterfactual_allocation,
                )
            )

        return scaled_assets

    @staticmethod
    def _resolve_recommended_currency(
        *,
        historical_allocation: PortfolioAllocationAsOf,
        recommended_original: PortfolioAllocationAssetAsOf | None,
    ) -> Currency:
        if recommended_original is not None:
            return recommended_original.currency

        if historical_allocation.currency is None:
            raise CounterfactualEmptyPortfolioError(
                "cannot determine currency for recommended asset from empty historical allocation"
            )

        return historical_allocation.currency

    @staticmethod
    def _sorted_assets(
        assets: list[PortfolioAllocationAssetAsOf],
    ) -> list[PortfolioAllocationAssetAsOf]:
        return sorted(
            assets,
            key=lambda asset: (
                asset.asset_symbol,
                asset.exchange.value if asset.exchange is not None else "",
                asset.asset_type.value if asset.asset_type is not None else "",
                asset.currency.value,
            ),
        )

    @staticmethod
    def _sorted_counterfactual_assets(
        assets: list[CounterfactualPortfolioAsset],
    ) -> list[CounterfactualPortfolioAsset]:
        return sorted(
            assets,
            key=lambda asset: (
                asset.asset_symbol,
                asset.exchange.value if asset.exchange is not None else "",
                asset.asset_type.value if asset.asset_type is not None else "",
                asset.currency.value,
            ),
        )
