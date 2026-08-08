from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.models.enums import Currency
from app.services.counterfactual_portfolio_construction_service import (
    CounterfactualPortfolio,
    CounterfactualPortfolioConstructionService,
)
from app.services.portfolio_allocation_as_of_service import (
    PortfolioAllocationAsOf,
    PortfolioAllocationAsOfService,
)


@dataclass(frozen=True)
class AstraHypotheticalValuationAsset:
    asset_symbol: str
    allocation: Decimal
    value: Decimal


@dataclass(frozen=True)
class AstraHypotheticalPortfolioValuation:
    as_of: datetime
    valuation_currency: Currency | None
    historical_portfolio_value: Decimal
    total_hypothetical_value: Decimal
    assets: list[AstraHypotheticalValuationAsset]


class AstraHypotheticalPortfolioValuationService:
    def __init__(
        self,
        counterfactual_portfolio_construction_service: CounterfactualPortfolioConstructionService,
        portfolio_allocation_as_of_service: PortfolioAllocationAsOfService,
    ) -> None:
        self.counterfactual_portfolio_construction_service = counterfactual_portfolio_construction_service
        self.portfolio_allocation_as_of_service = portfolio_allocation_as_of_service

    def valuate_for_recommendation(
        self,
        *,
        user_id: UUID,
        recommendation_id: UUID,
    ) -> AstraHypotheticalPortfolioValuation:
        counterfactual_portfolio = self.counterfactual_portfolio_construction_service.construct_for_recommendation(
            user_id=user_id,
            recommendation_id=recommendation_id,
        )

        historical_allocation_as_of = self.portfolio_allocation_as_of_service.get_portfolio_allocation_as_of(
            user_id=user_id,
            as_of=counterfactual_portfolio.as_of,
        )

        assets = self._calculate_asset_values(
            counterfactual_portfolio=counterfactual_portfolio,
            historical_allocation_as_of=historical_allocation_as_of,
        )

        total_hypothetical_value = sum((asset.value for asset in assets), Decimal("0"))

        return AstraHypotheticalPortfolioValuation(
            as_of=historical_allocation_as_of.as_of,
            valuation_currency=historical_allocation_as_of.currency,
            historical_portfolio_value=historical_allocation_as_of.total_value,
            total_hypothetical_value=total_hypothetical_value,
            assets=assets,
        )

    @staticmethod
    def _calculate_asset_values(
        *,
        counterfactual_portfolio: CounterfactualPortfolio,
        historical_allocation_as_of: PortfolioAllocationAsOf,
    ) -> list[AstraHypotheticalValuationAsset]:
        historical_portfolio_value = historical_allocation_as_of.total_value

        if not counterfactual_portfolio.assets:
            return []

        valued_assets: list[AstraHypotheticalValuationAsset] = []
        allocated_so_far = Decimal("0")

        for index, asset in enumerate(counterfactual_portfolio.assets):
            is_last = index == len(counterfactual_portfolio.assets) - 1

            if is_last:
                asset_value = historical_portfolio_value - allocated_so_far
            else:
                asset_value = asset.counterfactual_allocation * historical_portfolio_value
                allocated_so_far += asset_value

            valued_assets.append(
                AstraHypotheticalValuationAsset(
                    asset_symbol=asset.asset_symbol,
                    allocation=asset.counterfactual_allocation,
                    value=asset_value,
                )
            )

        return valued_assets
