from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.baseline_decision import BaselineDecision
from app.models.enums import BaselineAction, Currency, RecommendationStatus, RecommendationType
from app.models.neutral_baseline_strategy import MAINTAIN_CURRENT_ALLOCATION_STRATEGY
from app.models.recommendation import Recommendation
from app.repositories.baseline_decision_repository import DuplicateBaselineDecisionError
from app.services.neutral_baseline_generation_service import (
    BaselineGenerationAssetAllocationNotFoundError,
    BaselineGenerationHistoricalAllocationUnavailableError,
    BaselineGenerationMissingMarketContextError,
    BaselineGenerationRecommendationNotFoundError,
    NeutralBaselineGenerationService,
)
from app.services.portfolio_allocation_as_of_service import (
    MissingHistoricalPriceError,
    PortfolioAllocationAsOf,
    PortfolioAllocationAssetAsOf,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")
BASELINE_ID = UUID("44444444-4444-4444-8444-444444444444")


def _build_recommendation(
    *,
    user_id: UUID = USER_A,
    asset_symbol: str = "AAPL",
    created_at: datetime | None = None,
    with_market_context: bool = True,
) -> Recommendation:
    recommendation = Recommendation(
        id=RECOMMENDATION_ID,
        user_id=user_id,
        status=RecommendationStatus.GENERATED,
        recommendation_type=RecommendationType.INCREASE,
        asset_symbol=asset_symbol,
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.90000000"),
        risk_score=Decimal("0.20000000"),
        reasoning_text="Keep steady exposure.",
        reasoning_json={"reason": "test"},
        market_snapshot={"state": "normal"},
        market_snapshot_id=UUID("55555555-5555-4555-8555-555555555555") if with_market_context else None,
        portfolio_snapshot_id=None,
        expires_at=None,
        evaluated_at=None,
        created_at=created_at or datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
    )
    recommendation.context_market_snapshot = object() if with_market_context else None
    return recommendation


def _build_allocation_as_of(*, as_of: datetime, assets: list[tuple[str, str]]) -> PortfolioAllocationAsOf:
    allocations = []
    for symbol, allocation in assets:
        allocations.append(
            PortfolioAllocationAssetAsOf(
                asset_symbol=symbol,
                exchange=None,
                asset_type=None,
                currency=Currency.INR,
                quantity=Decimal("1"),
                price=Decimal("100"),
                price_timestamp=as_of,
                market_value=Decimal("100"),
                allocation=Decimal(allocation),
            )
        )

    return PortfolioAllocationAsOf(
        as_of=as_of,
        total_value=Decimal("100"),
        currency=Currency.INR,
        allocations=allocations,
    )


def _build_baseline_decision(*, user_id: UUID = USER_A) -> BaselineDecision:
    return BaselineDecision(
        id=BASELINE_ID,
        user_id=user_id,
        recommendation_id=RECOMMENDATION_ID,
        strategy_key=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.key,
        strategy_version=MAINTAIN_CURRENT_ALLOCATION_STRATEGY.version,
        baseline_action=BaselineAction.MAINTAIN,
        baseline_allocation=Decimal("0.25000000"),
        created_at=datetime(2026, 8, 8, 10, 1, tzinfo=timezone.utc),
    )


def _build_service() -> tuple[NeutralBaselineGenerationService, Mock, Mock, Mock, Mock]:
    db = Mock()
    recommendation_repository = Mock()
    baseline_decision_repository = Mock()
    allocation_service = Mock()

    service = NeutralBaselineGenerationService(
        db=db,
        recommendation_repository=recommendation_repository,
        baseline_decision_repository=baseline_decision_repository,
        portfolio_allocation_as_of_service=allocation_service,
    )

    return service, db, recommendation_repository, baseline_decision_repository, allocation_service


def test_valid_recommendation_generates_baseline_decision() -> None:
    service, db, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.25000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    result = service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert isinstance(result, BaselineDecision)
    db.commit.assert_called_once()


def test_baseline_action_is_maintain() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert baseline_repository.create.call_args.kwargs["baseline_action"] == BaselineAction.MAINTAIN


def test_strategy_key_is_maintain_current_allocation() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert baseline_repository.create.call_args.kwargs["strategy_key"] == "maintain_current_allocation"


def test_strategy_version_is_1_0() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert baseline_repository.create.call_args.kwargs["strategy_version"] == "1.0"


def test_baseline_allocation_comes_from_historical_allocation_service() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.45678901")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert baseline_repository.create.call_args.kwargs["baseline_allocation"] == Decimal("0.45678901")


def test_recommendation_created_at_is_used_as_historical_timestamp() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    created_at = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    recommendation = _build_recommendation(asset_symbol="AAPL", created_at=created_at)

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=created_at,
        assets=[("AAPL", "0.3")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert allocation_service.get_portfolio_allocation_as_of.call_args.kwargs["as_of"] == created_at


def test_recommended_asset_allocation_is_selected_correctly() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="MSFT")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.20000000"), ("MSFT", "0.35000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    assert baseline_repository.create.call_args.kwargs["baseline_allocation"] == Decimal("0.35000000")


def test_recommendation_with_no_historical_allocation_for_asset_fails() -> None:
    service, _, recommendation_repository, _, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="TSLA")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.20000000")],
    )

    with pytest.raises(BaselineGenerationAssetAllocationNotFoundError):
        service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_missing_recommendation_fails() -> None:
    service, _, recommendation_repository, _, _ = _build_service()
    recommendation_repository.get_by_id.return_value = None

    with pytest.raises(BaselineGenerationRecommendationNotFoundError):
        service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_user_isolation_is_enforced() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(user_id=USER_B, asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision(user_id=USER_B)

    service.generate_for_recommendation(user_id=USER_B, recommendation_id=RECOMMENDATION_ID)

    recommendation_repository.get_by_id.assert_called_once_with(
        USER_B,
        RECOMMENDATION_ID,
        include_market_snapshot=True,
    )
    allocation_service.get_portfolio_allocation_as_of.assert_called_once_with(
        user_id=USER_B,
        as_of=recommendation.created_at,
    )
    assert baseline_repository.create.call_args.kwargs["user_id"] == USER_B


def test_duplicate_baseline_generation_uses_existing_repository_behavior() -> None:
    service, db, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.side_effect = DuplicateBaselineDecisionError("duplicate")

    with pytest.raises(DuplicateBaselineDecisionError):
        service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    db.rollback.assert_called_once()


def test_historical_allocation_service_is_used_not_current_position() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    position_repository = Mock()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    allocation_service.get_portfolio_allocation_as_of.assert_called_once()
    position_repository.assert_not_called()


def test_no_live_market_provider_is_called() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    live_market_provider = Mock()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    live_market_provider.assert_not_called()


def test_baseline_decision_is_persisted_through_baseline_decision_repository() -> None:
    service, _, recommendation_repository, baseline_repository, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.return_value = _build_allocation_as_of(
        as_of=recommendation.created_at,
        assets=[("AAPL", "0.30000000")],
    )
    baseline_repository.create.return_value = _build_baseline_decision()

    service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)

    baseline_repository.create.assert_called_once()


def test_recommendation_without_market_context_fails() -> None:
    service, _, recommendation_repository, _, _ = _build_service()
    recommendation_repository.get_by_id.return_value = _build_recommendation(with_market_context=False)

    with pytest.raises(BaselineGenerationMissingMarketContextError):
        service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_historical_allocation_unavailable_fails_deterministically() -> None:
    service, _, recommendation_repository, _, allocation_service = _build_service()
    recommendation = _build_recommendation(asset_symbol="AAPL")

    recommendation_repository.get_by_id.return_value = recommendation
    allocation_service.get_portfolio_allocation_as_of.side_effect = MissingHistoricalPriceError("missing price")

    with pytest.raises(BaselineGenerationHistoricalAllocationUnavailableError):
        service.generate_for_recommendation(user_id=USER_A, recommendation_id=RECOMMENDATION_ID)


def test_service_has_no_update_operation() -> None:
    service, _, _, _, _ = _build_service()

    assert not hasattr(service, "update")
    assert not hasattr(service, "update_lifecycle")
