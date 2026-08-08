from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.models.enums import AssetType, Currency, Exchange
from app.repositories.market_snapshot_repository import MarketSnapshotRepository
from app.services.historical_holdings_service import (
    HistoricalHoldingsService,
    NaiveAsOfDatetimeError,
)


class MissingHistoricalPriceError(ValueError):
    """Raised when no historical price is available at or before as_of."""


class UnsupportedMultiCurrencyValuationError(ValueError):
    """Raised when historical valuation requires FX conversion that is unsupported."""


class InvalidHoldingQuantityError(ValueError):
    """Raised when a holding has an invalid negative quantity."""


class NonPositivePortfolioValueError(ValueError):
    """Raised when computed total portfolio value is not positive."""


@dataclass(frozen=True)
class PortfolioAllocationAssetAsOf:
    asset_symbol: str
    exchange: Exchange | None
    asset_type: AssetType | None
    currency: Currency
    quantity: Decimal
    price: Decimal
    price_timestamp: datetime
    market_value: Decimal
    allocation: Decimal


@dataclass(frozen=True)
class PortfolioAllocationAsOf:
    as_of: datetime
    total_value: Decimal
    currency: Currency | None
    allocations: list[PortfolioAllocationAssetAsOf]


class PortfolioAllocationAsOfService:
    def __init__(
        self,
        historical_holdings_service: HistoricalHoldingsService,
        market_snapshot_repository: MarketSnapshotRepository,
    ):
        self.historical_holdings_service = historical_holdings_service
        self.market_snapshot_repository = market_snapshot_repository

    def get_portfolio_allocation_as_of(
        self,
        *,
        user_id: UUID,
        as_of: datetime,
    ) -> PortfolioAllocationAsOf:
        as_of_utc = self._normalize_as_of_to_utc(as_of)

        holdings = self.historical_holdings_service.get_holdings_as_of(
            user_id=user_id,
            as_of=as_of_utc,
        )

        if not holdings:
            return PortfolioAllocationAsOf(
                as_of=as_of_utc,
                total_value=Decimal("0"),
                currency=None,
                allocations=[],
            )

        valued_assets: list[PortfolioAllocationAssetAsOf] = []
        currencies: set[Currency] = set()

        ordered_holdings = sorted(
            holdings,
            key=lambda holding: (
                holding.asset_symbol,
                holding.exchange.value if holding.exchange is not None else "",
                holding.asset_type.value if holding.asset_type is not None else "",
                holding.currency.value,
            ),
        )

        for holding in ordered_holdings:
            quantity = holding.remaining_quantity

            if quantity == 0:
                continue

            if quantity < 0:
                raise InvalidHoldingQuantityError(
                    f"Negative quantity is not supported for historical valuation: {holding.asset_symbol}"
                )

            currencies.add(holding.currency)

            snapshot = self.market_snapshot_repository.get_latest_price_at_or_before(
                user_id=user_id,
                asset_symbol=holding.asset_symbol,
                as_of=as_of_utc,
            )

            if snapshot is None:
                raise MissingHistoricalPriceError(
                    f"No historical market snapshot available at or before as_of for {holding.asset_symbol}"
                )

            market_value = quantity * snapshot.asset_price

            valued_assets.append(
                PortfolioAllocationAssetAsOf(
                    asset_symbol=holding.asset_symbol,
                    exchange=holding.exchange,
                    asset_type=holding.asset_type,
                    currency=holding.currency,
                    quantity=quantity,
                    price=snapshot.asset_price,
                    price_timestamp=snapshot.price_timestamp,
                    market_value=market_value,
                    allocation=Decimal("0"),
                )
            )

        if not valued_assets:
            return PortfolioAllocationAsOf(
                as_of=as_of_utc,
                total_value=Decimal("0"),
                currency=None,
                allocations=[],
            )

        if len(currencies) > 1:
            raise UnsupportedMultiCurrencyValuationError(
                "Historical valuation across multiple currencies requires FX conversion, which is unsupported"
            )

        total_value = sum((asset.market_value for asset in valued_assets), Decimal("0"))

        if total_value <= 0:
            raise NonPositivePortfolioValueError("Total historical portfolio value must be positive")

        allocations = [
            PortfolioAllocationAssetAsOf(
                asset_symbol=asset.asset_symbol,
                exchange=asset.exchange,
                asset_type=asset.asset_type,
                currency=asset.currency,
                quantity=asset.quantity,
                price=asset.price,
                price_timestamp=asset.price_timestamp,
                market_value=asset.market_value,
                allocation=asset.market_value / total_value,
            )
            for asset in valued_assets
        ]

        single_currency = next(iter(currencies))

        return PortfolioAllocationAsOf(
            as_of=as_of_utc,
            total_value=total_value,
            currency=single_currency,
            allocations=allocations,
        )

    @staticmethod
    def _normalize_as_of_to_utc(as_of: datetime) -> datetime:
        if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
            raise NaiveAsOfDatetimeError("as_of must be timezone-aware")

        return as_of.astimezone(timezone.utc)
