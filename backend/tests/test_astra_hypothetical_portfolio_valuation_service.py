from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import AssetType, Currency, Exchange
from app.services.astra_hypothetical_portfolio_valuation_service import (
    AstraHypotheticalPortfolioValuationService,
)
from app.services.counterfactual_portfolio_construction_service import (
    CounterfactualPortfolio,
    CounterfactualPortfolioAsset,
    CounterfactualPortfolioConstructionService,
)
from app.services.portfolio_allocation_as_of_service import (
    MissingHistoricalPriceError,
    PortfolioAllocationAsOf,
    PortfolioAllocationAssetAsOf,
    UnsupportedMultiCurrencyValuationError,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")


def _counterfactual_asset(*, symbol: str, allocation: str) -> CounterfactualPortfolioAsset:
    return CounterfactualPortfolioAsset(
        asset_symbol=symbol,
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        original_allocation=Decimal("0"),
        counterfactual_allocation=Decimal(allocation),
    )


def _counterfactual_portfolio(
    *,
    as_of: datetime,
    assets: list[CounterfactualPortfolioAsset],
) -> CounterfactualPortfolio:
    return CounterfactualPortfolio(
        as_of=as_of,
        total_allocation=sum((asset.counterfactual_allocation for asset in assets), Decimal("0")),
        assets=assets,
    )


def _allocation_as_of(*, as_of: datetime, total_value: str) -> PortfolioAllocationAsOf:
    return PortfolioAllocationAsOf(
        as_of=as_of,
        total_value=Decimal(total_value),
        currency=Currency.INR,
        allocations=[
            PortfolioAllocationAssetAsOf(
                asset_symbol="AAPL",
                exchange=Exchange.NSE,
                asset_type=AssetType.STOCK,
                currency=Currency.INR,
                quantity=Decimal("1"),
                price=Decimal("100"),
                price_timestamp=as_of,
                market_value=Decimal("100"),
                allocation=Decimal("1"),
            )
        ],
    )


def _build_service() -> tuple[AstraHypotheticalPortfolioValuationService, Mock, Mock]:
    counterfactual_service = Mock()
    allocation_service = Mock()
    service = AstraHypotheticalPortfolioValuationService(
        counterfactual_portfolio_construction_service=counterfactual_service,
        portfolio_allocation_as_of_service=allocation_service,
    )
    return service, counterfactual_service, allocation_service


def test_example_hypothetical_valuation_matches_expected_values() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[
            _counterfactual_asset(symbol="MSFT", allocation="0.10"),
            _counterfactual_asset(symbol="AAPL", allocation="0.20"),
            _counterfactual_asset(symbol="CASH", allocation="0.70"),
        ],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=t,
        total_value="100000.00",
    )

    result = service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert result.historical_portfolio_value == Decimal("100000.00")
    assert result.total_hypothetical_value == Decimal("100000.00")

    msft = next(asset for asset in result.assets if asset.asset_symbol == "MSFT")
    aapl = next(asset for asset in result.assets if asset.asset_symbol == "AAPL")
    cash = next(asset for asset in result.assets if asset.asset_symbol == "CASH")

    assert msft.value == Decimal("10000.0000")
    assert aapl.value == Decimal("20000.0000")
    assert cash.value == Decimal("70000.0000")


def test_recommendation_created_at_is_used_as_historical_timestamp() -> None:
    recommendation_repository = Mock()
    allocation_service = Mock()

    recommendation_created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=recommendation_created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    historical_allocation = PortfolioAllocationAsOf(
        as_of=recommendation_created_at,
        total_value=Decimal("1000"),
        currency=Currency.INR,
        allocations=[
            PortfolioAllocationAssetAsOf(
                asset_symbol="AAPL",
                exchange=Exchange.NSE,
                asset_type=AssetType.STOCK,
                currency=Currency.INR,
                quantity=Decimal("1"),
                price=Decimal("100"),
                price_timestamp=recommendation_created_at,
                market_value=Decimal("100"),
                allocation=Decimal("1"),
            )
        ],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = historical_allocation

    counterfactual_service = CounterfactualPortfolioConstructionService(
        recommendation_repository=recommendation_repository,
        portfolio_allocation_as_of_service=allocation_service,
    )

    service = AstraHypotheticalPortfolioValuationService(
        counterfactual_portfolio_construction_service=counterfactual_service,
        portfolio_allocation_as_of_service=allocation_service,
    )

    service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert allocation_service.get_portfolio_allocation_as_of.call_count == 2
    for call in allocation_service.get_portfolio_allocation_as_of.call_args_list:
        assert call.kwargs["as_of"] == recommendation_created_at
        assert call.kwargs["user_id"] == USER_A


def test_historical_portfolio_value_is_sourced_from_allocation_service_total_value() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[_counterfactual_asset(symbol="MSFT", allocation="1")],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=t,
        total_value="123456.78",
    )

    result = service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert result.historical_portfolio_value == Decimal("123456.78")
    assert result.assets[0].value == Decimal("123456.78")


def test_counterfactual_allocations_are_used_without_reconstruction() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[
            _counterfactual_asset(symbol="MSFT", allocation="0.333333333333333333"),
            _counterfactual_asset(symbol="AAPL", allocation="0.666666666666666667"),
        ],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=t,
        total_value="300",
    )

    result = service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    msft = next(asset for asset in result.assets if asset.asset_symbol == "MSFT")
    aapl = next(asset for asset in result.assets if asset.asset_symbol == "AAPL")

    assert msft.allocation == Decimal("0.333333333333333333")
    assert aapl.allocation == Decimal("0.666666666666666667")
    assert result.total_hypothetical_value == Decimal("300")


def test_user_isolation_is_preserved_in_both_dependency_calls() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[_counterfactual_asset(symbol="AAPL", allocation="1")],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(as_of=t, total_value="100")

    service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    counterfactual_service.construct_for_recommendation.assert_called_once_with(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
    )
    allocation_service.get_portfolio_allocation_as_of.assert_called_once_with(
        user_id=USER_A,
        as_of=t,
    )


def test_missing_historical_valuation_context_fails_deterministically() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[_counterfactual_asset(symbol="AAPL", allocation="1")],
    )
    allocation_service.get_portfolio_allocation_as_of.side_effect = MissingHistoricalPriceError("missing")

    with pytest.raises(MissingHistoricalPriceError):
        service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_multi_currency_behavior_follows_existing_deterministic_policy() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[_counterfactual_asset(symbol="AAPL", allocation="1")],
    )
    allocation_service.get_portfolio_allocation_as_of.side_effect = UnsupportedMultiCurrencyValuationError("fx")

    with pytest.raises(UnsupportedMultiCurrencyValuationError):
        service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_future_trade_and_future_snapshot_state_are_not_used_by_this_phase() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    live_market_provider = Mock()
    trade_repository = Mock()
    position_repository = Mock()

    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[_counterfactual_asset(symbol="AAPL", allocation="1")],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(as_of=t, total_value="100")

    service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    allocation_service.get_portfolio_allocation_as_of.assert_called_once_with(user_id=USER_A, as_of=t)
    live_market_provider.assert_not_called()
    trade_repository.assert_not_called()
    position_repository.assert_not_called()


def test_decimal_arithmetic_is_preserved_without_float_conversion() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[
            _counterfactual_asset(symbol="MSFT", allocation="0.1"),
            _counterfactual_asset(symbol="AAPL", allocation="0.2"),
            _counterfactual_asset(symbol="CASH", allocation="0.7"),
        ],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=t,
        total_value="0.3",
    )

    result = service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert all(isinstance(asset.value, Decimal) for asset in result.assets)
    assert result.total_hypothetical_value == Decimal("0.3")


def test_asset_values_sum_to_historical_portfolio_value_with_residual_handling() -> None:
    service, counterfactual_service, allocation_service = _build_service()
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    counterfactual_service.construct_for_recommendation.return_value = _counterfactual_portfolio(
        as_of=t,
        assets=[
            _counterfactual_asset(symbol="MSFT", allocation="0.333333333333333333"),
            _counterfactual_asset(symbol="AAPL", allocation="0.333333333333333333"),
            _counterfactual_asset(symbol="CASH", allocation="0.333333333333333334"),
        ],
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=t,
        total_value="100",
    )

    result = service.valuate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert sum((asset.value for asset in result.assets), Decimal("0")) == Decimal("100")
    assert result.total_hypothetical_value == result.historical_portfolio_value


def test_service_introduces_no_persistence_or_trade_execution_behavior() -> None:
    service, _, _ = _build_service()

    assert not hasattr(service, "db")
    assert not hasattr(service, "commit")
    assert not hasattr(service, "execute_trade")
