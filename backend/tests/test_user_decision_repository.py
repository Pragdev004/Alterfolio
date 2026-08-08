from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    RecommendationStatus,
    RecommendationType,
    TradeSource,
    TransactionType,
    UserDecisionType,
)
from app.models.recommendation import Recommendation
from app.models.trade import Trade
from app.models.user_decision import UserDecision
from app.repositories.user_decision_repository import (
    DuplicateUserDecisionError,
    UserDecisionRecommendationNotFoundError,
    UserDecisionRepository,
    UserDecisionTradeNotFoundError,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
RECOMMENDATION_ID = UUID("33333333-3333-4333-8333-333333333333")
TRADE_ID = UUID("44444444-4444-4444-8444-444444444444")
DECISION_ID = UUID("55555555-5555-4555-8555-555555555555")


def _build_recommendation(*, user_id: UUID = USER_A) -> Recommendation:
    return Recommendation(
        id=RECOMMENDATION_ID,
        user_id=user_id,
        status=RecommendationStatus.GENERATED,
        recommendation_type=RecommendationType.BUY,
        asset_symbol="AAPL",
        suggested_allocation=Decimal("0.25000000"),
        expected_holding_period_days=30,
        confidence_score=Decimal("0.85000000"),
        risk_score=Decimal("0.30000000"),
        reasoning_text="Momentum and earnings quality.",
        reasoning_json={"signals": ["momentum", "earnings"]},
        market_snapshot={"index_trend": "up"},
        market_snapshot_id=None,
        portfolio_snapshot_id=None,
        expires_at=None,
        evaluated_at=None,
        created_at=datetime.now(timezone.utc),
    )


def _build_trade(*, user_id: UUID = USER_A) -> Trade:
    return Trade(
        id=TRADE_ID,
        user_id=user_id,
        asset_symbol="AAPL",
        asset_name="Apple Inc",
        asset_type=AssetType.STOCK,
        exchange=Exchange.NSE,
        currency=Currency.INR,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("10"),
        price_per_unit=Decimal("200"),
        trade_timestamp=datetime.now(timezone.utc),
        brokerage_fee=Decimal("0"),
        taxes=Decimal("0"),
        broker=None,
        order_id=None,
        trade_source=TradeSource.MANUAL,
        market_session=MarketSession.REGULAR,
        investment_horizon=None,
        notes=None,
    )


def _build_decision(*, user_id: UUID = USER_A, decision_type: UserDecisionType = UserDecisionType.ACCEPTED) -> UserDecision:
    return UserDecision(
        id=DECISION_ID,
        user_id=user_id,
        recommendation_id=RECOMMENDATION_ID,
        trade_id=None,
        decision_type=decision_type,
        decided_at=datetime.now(timezone.utc),
        modified_allocation=None,
        decision_note=None,
    )


def _assert_user_filter_present(filter_args: tuple[object, ...], user_id: UUID) -> None:
    assert any(
        getattr(arg.left, "name", "") == "user_id" and arg.right.value == user_id
        for arg in filter_args
    )


def test_create_accepted_decision() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.ACCEPTED,
    )

    assert isinstance(created, UserDecision)
    assert created.decision_type == UserDecisionType.ACCEPTED
    assert created.trade_id is None
    db.add.assert_called_once_with(created)


def test_create_ignored_decision() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.IGNORED,
    )

    assert created.decision_type == UserDecisionType.IGNORED


def test_create_modified_decision() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.MODIFIED,
        modified_allocation=Decimal("0.33333333"),
        decision_note="Reduced allocation due to concentration.",
    )

    assert created.decision_type == UserDecisionType.MODIFIED
    assert created.modified_allocation == Decimal("0.33333333")
    assert created.decision_note == "Reduced allocation due to concentration."


def test_create_decision_with_valid_trade_reference() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    trade_query = Mock()
    trade_query.filter.return_value = trade_query
    trade_query.first.return_value = _build_trade()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, trade_query, duplicate_query]

    repository = UserDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.ACCEPTED,
        trade_id=TRADE_ID,
    )

    assert created.trade_id == TRADE_ID


def test_create_decision_without_trade_reference() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)
    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.IGNORED,
        trade_id=None,
    )

    assert created.trade_id is None


def test_create_rejects_recommendation_user_mismatch() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = None

    db = Mock()
    db.query.return_value = recommendation_query

    repository = UserDecisionRepository(db)

    with pytest.raises(UserDecisionRecommendationNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            decision_type=UserDecisionType.ACCEPTED,
        )

    filter_args = recommendation_query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_create_rejects_trade_user_mismatch() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    trade_query = Mock()
    trade_query.filter.return_value = trade_query
    trade_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, trade_query]

    repository = UserDecisionRepository(db)

    with pytest.raises(UserDecisionTradeNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            decision_type=UserDecisionType.ACCEPTED,
            trade_id=TRADE_ID,
        )

    filter_args = trade_query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_create_rejects_missing_recommendation() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = None

    db = Mock()
    db.query.return_value = recommendation_query

    repository = UserDecisionRepository(db)

    with pytest.raises(UserDecisionRecommendationNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            decision_type=UserDecisionType.IGNORED,
        )


def test_create_rejects_missing_trade_when_trade_id_supplied() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    trade_query = Mock()
    trade_query.filter.return_value = trade_query
    trade_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, trade_query]

    repository = UserDecisionRepository(db)

    with pytest.raises(UserDecisionTradeNotFoundError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            decision_type=UserDecisionType.MODIFIED,
            trade_id=TRADE_ID,
        )


def test_create_rejects_duplicate_decision_for_same_recommendation() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = _build_decision()

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)

    with pytest.raises(DuplicateUserDecisionError):
        repository.create(
            user_id=USER_A,
            recommendation_id=RECOMMENDATION_ID,
            decision_type=UserDecisionType.ACCEPTED,
        )


def test_get_by_id_is_user_scoped() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_decision()

    db = Mock()
    db.query.return_value = query

    repository = UserDecisionRepository(db)
    result = repository.get_by_id(USER_A, DECISION_ID)

    assert result is not None
    assert result.user_id == USER_A

    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_get_for_recommendation_is_user_scoped() -> None:
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = _build_decision()

    db = Mock()
    db.query.return_value = query

    repository = UserDecisionRepository(db)
    result = repository.get_for_recommendation(USER_A, RECOMMENDATION_ID)

    assert result is not None
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_list_for_user_is_user_scoped() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [_build_decision()]

    db = Mock()
    db.query.return_value = query

    repository = UserDecisionRepository(db)
    results = repository.list_for_user(USER_A)

    assert len(results) == 1
    filter_args = query.filter.call_args.args
    _assert_user_filter_present(filter_args, USER_A)


def test_modified_allocation_preserves_decimal_precision() -> None:
    recommendation_query = Mock()
    recommendation_query.filter.return_value = recommendation_query
    recommendation_query.first.return_value = _build_recommendation()

    duplicate_query = Mock()
    duplicate_query.filter.return_value = duplicate_query
    duplicate_query.first.return_value = None

    db = Mock()
    db.query.side_effect = [recommendation_query, duplicate_query]

    repository = UserDecisionRepository(db)
    precise_value = Decimal("0.12345678")

    created = repository.create(
        user_id=USER_A,
        recommendation_id=RECOMMENDATION_ID,
        decision_type=UserDecisionType.MODIFIED,
        modified_allocation=precise_value,
    )

    assert created.modified_allocation == precise_value


def test_repository_has_no_update_method() -> None:
    repository = UserDecisionRepository(Mock())

    assert not hasattr(repository, "update")
    assert not hasattr(repository, "update_lifecycle")
