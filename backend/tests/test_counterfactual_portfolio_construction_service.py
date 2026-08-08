from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import AssetType, Currency, Exchange
from app.services.counterfactual_portfolio_construction_service import (
    CounterfactualEmptyPortfolioError,
    CounterfactualHistoricalAllocationUnavailableError,
    CounterfactualInsufficientNonRecommendedAllocationError,
    CounterfactualPortfolioConstructionService,
    CounterfactualRecommendationNotFoundError,
    CounterfactualRecommendedAssetAmbiguousError,
    CounterfactualUnsupportedMultiCurrencyError,
    InvalidCounterfactualSuggestedAllocationError,
)
from app.services.portfolio_allocation_as_of_service import (
    PortfolioAllocationAsOf,
    PortfolioAllocationAssetAsOf,
    UnsupportedMultiCurrencyValuationError,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")


class FakeCurrency(str, Enum):
    USD = "USD"


def _asset(
    *,
    symbol: str,
    allocation: str,
    exchange: Exchange | None = Exchange.NSE,
    asset_type: AssetType | None = AssetType.STOCK,
    currency: Currency | FakeCurrency = Currency.INR,
) -> PortfolioAllocationAssetAsOf:
    return PortfolioAllocationAssetAsOf(
        asset_symbol=symbol,
        exchange=exchange,
        asset_type=asset_type,
        currency=currency,
        quantity=Decimal("1"),
        price=Decimal("100"),
        price_timestamp=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
        market_value=Decimal("100"),
        allocation=Decimal(allocation),
    )


def _allocation_as_of(*, as_of: datetime, assets: list[PortfolioAllocationAssetAsOf]) -> PortfolioAllocationAsOf:
    return PortfolioAllocationAsOf(
        as_of=as_of,
        total_value=Decimal("100"),
        currency=assets[0].currency if assets else None,
        allocations=assets,
    )


def _build_service() -> tuple[CounterfactualPortfolioConstructionService, Mock, Mock]:
    recommendation_repository = Mock()
    allocation_service = Mock()
    service = CounterfactualPortfolioConstructionService(
        recommendation_repository=recommendation_repository,
        portfolio_allocation_as_of_service=allocation_service,
    )
    return service, recommendation_repository, allocation_service


def test_existing_recommended_asset_target_increase() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.05"),
                _asset(symbol="AAPL", allocation="0.20"),
                _asset(symbol="CASH", allocation="0.75", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    assert msft.counterfactual_allocation == Decimal("0.10")


def test_existing_recommended_asset_target_decrease() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.50"),
                _asset(symbol="AAPL", allocation="0.30"),
                _asset(symbol="CASH", allocation="0.20", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.25"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    assert msft.counterfactual_allocation == Decimal("0.25")


def test_recommended_asset_absent_from_portfolio_is_added_once() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="AAPL", allocation="0.30"),
                _asset(symbol="CASH", allocation="0.70", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    msft_assets = [item for item in result.assets if item.asset_symbol == "MSFT"]
    assert len(msft_assets) == 1
    assert msft_assets[0].original_allocation == Decimal("0")
    assert msft_assets[0].counterfactual_allocation == Decimal("0.10")


def test_target_allocation_zero_sets_recommended_asset_to_zero() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.30"),
                _asset(symbol="AAPL", allocation="0.70"),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    assert msft.counterfactual_allocation == Decimal("0")
    assert result.total_allocation == Decimal("1")


def test_target_allocation_one_sets_other_assets_to_zero() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.30"),
                _asset(symbol="AAPL", allocation="0.70"),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("1"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    aapl = next(item for item in result.assets if item.asset_symbol == "AAPL")

    assert msft.counterfactual_allocation == Decimal("1")
    assert aapl.counterfactual_allocation == Decimal("0")
    assert result.total_allocation == Decimal("1")


def test_non_recommended_assets_are_redistributed_proportionally() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.10"),
                _asset(symbol="AAPL", allocation="0.20"),
                _asset(symbol="GOOG", allocation="0.30"),
                _asset(symbol="CASH", allocation="0.40", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.25"),
    )

    aapl = next(item for item in result.assets if item.asset_symbol == "AAPL")
    goog = next(item for item in result.assets if item.asset_symbol == "GOOG")
    cash = next(item for item in result.assets if item.asset_symbol == "CASH")

    non_recommended_total = Decimal("0.90")
    remaining = Decimal("0.75")

    assert aapl.counterfactual_allocation == (Decimal("0.20") / non_recommended_total) * remaining
    assert cash.counterfactual_allocation == (Decimal("0.40") / non_recommended_total) * remaining
    assert goog.counterfactual_allocation == remaining - aapl.counterfactual_allocation - cash.counterfactual_allocation


def test_result_allocations_sum_correctly() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[_asset(symbol="MSFT", allocation="0.05"), _asset(symbol="AAPL", allocation="0.95")],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    total = sum((item.counterfactual_allocation for item in result.assets), Decimal("0"))
    assert total == Decimal("1")
    assert result.total_allocation == Decimal("1")


def test_original_allocations_are_preserved_in_output() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[_asset(symbol="MSFT", allocation="0.05"), _asset(symbol="AAPL", allocation="0.95")],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    aapl = next(item for item in result.assets if item.asset_symbol == "AAPL")

    assert msft.original_allocation == Decimal("0.05")
    assert aapl.original_allocation == Decimal("0.95")


def test_recommended_asset_appears_exactly_once_in_result() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[_asset(symbol="AAPL", allocation="1")],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.2"),
    )

    assert len([asset for asset in result.assets if asset.asset_symbol == "MSFT"]) == 1


def test_empty_portfolio_with_target_greater_than_zero_fails() -> None:
    service, _, _ = _build_service()

    with pytest.raises(CounterfactualEmptyPortfolioError):
        service.construct_from_historical_allocation(
            historical_allocation=_allocation_as_of(
                as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
                assets=[],
            ),
            recommended_asset_symbol="MSFT",
            suggested_allocation=Decimal("0.10"),
        )


def test_empty_portfolio_with_target_zero_is_deterministic() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0"),
    )

    assert result.assets == []
    assert result.total_allocation == Decimal("0")


def test_no_non_recommended_allocation_while_target_less_than_one_fails() -> None:
    service, _, _ = _build_service()

    with pytest.raises(CounterfactualInsufficientNonRecommendedAllocationError):
        service.construct_from_historical_allocation(
            historical_allocation=_allocation_as_of(
                as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
                assets=[_asset(symbol="MSFT", allocation="1")],
            ),
            recommended_asset_symbol="MSFT",
            suggested_allocation=Decimal("0.80"),
        )


def test_decimal_precision_is_preserved_without_float_artifacts() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.1"),
                _asset(symbol="AAPL", allocation="0.2"),
                _asset(symbol="CASH", allocation="0.7", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.333333333333333333"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    assert isinstance(msft.counterfactual_allocation, Decimal)
    assert msft.counterfactual_allocation == Decimal("0.333333333333333333")


def test_float_input_is_rejected_to_prevent_float_conversion() -> None:
    service, _, _ = _build_service()

    with pytest.raises(InvalidCounterfactualSuggestedAllocationError):
        service.construct_from_historical_allocation(
            historical_allocation=_allocation_as_of(
                as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
                assets=[_asset(symbol="AAPL", allocation="1")],
            ),
            recommended_asset_symbol="MSFT",
            suggested_allocation=0.1,  # type: ignore[arg-type]
        )


def test_multiple_currencies_fail_deterministically_without_fx() -> None:
    service, _, _ = _build_service()

    with pytest.raises(CounterfactualUnsupportedMultiCurrencyError):
        service.construct_from_historical_allocation(
            historical_allocation=_allocation_as_of(
                as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
                assets=[
                    _asset(symbol="AAPL", allocation="0.5", currency=Currency.INR),
                    _asset(symbol="MSFT", allocation="0.5", currency=FakeCurrency.USD),
                ],
            ),
            recommended_asset_symbol="MSFT",
            suggested_allocation=Decimal("0.5"),
        )


def test_user_isolation_when_loading_recommendation() -> None:
    service, recommendation_repository, allocation_service = _build_service()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=created_at,
        assets=[_asset(symbol="AAPL", allocation="1")],
    )

    service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    recommendation_repository.get_by_id.assert_called_once_with(USER_A, RECOMMENDATION_ID)
    allocation_service.get_portfolio_allocation_as_of.assert_called_once_with(
        user_id=USER_A,
        as_of=created_at,
    )


def test_missing_recommendation_fails_with_user_scoped_lookup() -> None:
    service, recommendation_repository, _ = _build_service()
    recommendation_repository.get_by_id.return_value = None

    with pytest.raises(CounterfactualRecommendationNotFoundError):
        service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_historical_allocation_service_is_reused_not_current_positions() -> None:
    service, recommendation_repository, allocation_service = _build_service()
    position_repository = Mock()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=created_at,
        assets=[_asset(symbol="AAPL", allocation="1")],
    )

    service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    allocation_service.get_portfolio_allocation_as_of.assert_called_once()
    position_repository.assert_not_called()


def test_no_trades_are_created_or_modified() -> None:
    service, recommendation_repository, allocation_service = _build_service()
    trade_repository = Mock()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=created_at,
        assets=[_asset(symbol="AAPL", allocation="1")],
    )

    service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    trade_repository.assert_not_called()


def test_no_live_market_provider_is_called() -> None:
    service, recommendation_repository, allocation_service = _build_service()
    live_market_provider = Mock()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )
    allocation_service.get_portfolio_allocation_as_of.return_value = _allocation_as_of(
        as_of=created_at,
        assets=[_asset(symbol="AAPL", allocation="1")],
    )

    service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    live_market_provider.assert_not_called()


def test_result_ordering_is_deterministic() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="ZZZ", allocation="0.60"),
                _asset(symbol="AAA", allocation="0.40"),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    assert [asset.asset_symbol for asset in result.assets] == ["AAA", "MSFT", "ZZZ"]


def test_service_introduces_no_database_persistence_behavior() -> None:
    service, _, _ = _build_service()

    assert not hasattr(service, "db")
    assert not hasattr(service, "commit")


def test_example_no_hindsight_scenario_matches_expected_allocations() -> None:
    service, _, _ = _build_service()

    result = service.construct_from_historical_allocation(
        historical_allocation=_allocation_as_of(
            as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            assets=[
                _asset(symbol="MSFT", allocation="0.05"),
                _asset(symbol="AAPL", allocation="0.20"),
                _asset(symbol="CASH", allocation="0.75", asset_type=AssetType.CASH, exchange=None),
            ],
        ),
        recommended_asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )

    msft = next(item for item in result.assets if item.asset_symbol == "MSFT")
    aapl = next(item for item in result.assets if item.asset_symbol == "AAPL")
    cash = next(item for item in result.assets if item.asset_symbol == "CASH")

    assert msft.counterfactual_allocation == Decimal("0.10")
    assert aapl.counterfactual_allocation == (Decimal("0.20") / Decimal("0.95")) * Decimal("0.90")
    assert cash.counterfactual_allocation == Decimal("0.90") - aapl.counterfactual_allocation
    assert result.total_allocation == Decimal("1")


def test_ambiguous_recommended_asset_entries_fail_deterministically() -> None:
    service, _, _ = _build_service()

    with pytest.raises(CounterfactualRecommendedAssetAmbiguousError):
        service.construct_from_historical_allocation(
            historical_allocation=_allocation_as_of(
                as_of=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
                assets=[
                    _asset(symbol="MSFT", allocation="0.20", exchange=Exchange.NSE),
                    _asset(symbol="MSFT", allocation="0.30", exchange=Exchange.BSE),
                    _asset(symbol="AAPL", allocation="0.50"),
                ],
            ),
            recommended_asset_symbol="MSFT",
            suggested_allocation=Decimal("0.10"),
        )


def test_historical_allocation_unavailable_is_wrapped_deterministically() -> None:
    service, recommendation_repository, allocation_service = _build_service()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation_repository.get_by_id.return_value = SimpleNamespace(
        id=RECOMMENDATION_ID,
        user_id=USER_A,
        created_at=created_at,
        asset_symbol="MSFT",
        suggested_allocation=Decimal("0.10"),
    )
    allocation_service.get_portfolio_allocation_as_of.side_effect = UnsupportedMultiCurrencyValuationError("fx")

    with pytest.raises(CounterfactualHistoricalAllocationUnavailableError):
        service.construct_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)
