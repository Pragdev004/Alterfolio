from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

from app.models.enums import (
    AssetType,
    Exchange,
    MarketSession,
    TradeSource,
    TransactionType,
)
from app.models.trade import Trade
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


def _build_trade(symbol: str) -> TradeCreate:
    return TradeCreate(
        user_id=USER_B,
        asset_symbol=symbol,
        asset_name=f"{symbol} Ltd",
        asset_type=AssetType.STOCK,
        exchange=Exchange.NSE,
        transaction_type=TransactionType.BUY,
        quantity=Decimal("1"),
        price_per_unit=Decimal("100"),
        trade_timestamp=datetime.now(timezone.utc),
        trade_source=TradeSource.MANUAL,
        market_session=MarketSession.REGULAR,
    )


def test_trade_repository_create_ignores_payload_user_id() -> None:
    db = Mock()
    repository = TradeRepository(db)

    created = repository.create(_build_trade("TCS"), USER_A)

    assert isinstance(created, Trade)
    assert created.user_id == USER_A
    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(created)


def test_trade_repository_scopes_get_and_list_queries_to_user() -> None:
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.first.return_value = None
    query.all.return_value = []

    db = Mock()
    db.query.return_value = query

    repository = TradeRepository(db)
    repository.get_by_id(UUID("33333333-3333-4333-8333-333333333333"), USER_A)
    repository.list_all(USER_A)

    filter_calls = query.filter.call_args_list
    assert len(filter_calls) == 2

    get_call_args = filter_calls[0].args
    list_call_args = filter_calls[1].args

    assert any(getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_A for arg in get_call_args)
    assert any(getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_A for arg in list_call_args)


def test_portfolio_repository_scopes_summary_query_to_user() -> None:
    count_query = Mock()
    count_query.filter.return_value = count_query
    count_query.count.return_value = 1

    holdings_query = Mock()
    holdings_query.filter.return_value = holdings_query
    holdings_query.group_by.return_value = holdings_query
    holdings_query.having.return_value = holdings_query
    holdings_query.all.return_value = [
        SimpleNamespace(
            symbol="TCS",
            quantity=Decimal("2"),
            average_buy_price=Decimal("100"),
            invested_amount=Decimal("200"),
        )
    ]

    db = Mock()
    db.query.side_effect = [count_query, holdings_query]

    repository = PortfolioRepository(db)
    summary = repository.get_summary(USER_A)

    count_filter_args = count_query.filter.call_args.args
    holdings_filter_args = holdings_query.filter.call_args.args

    assert any(getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_A for arg in count_filter_args)
    assert any(getattr(arg.left, "name", "") == "user_id" and arg.right.value == USER_A for arg in holdings_filter_args)
    assert summary.total_trades == 1
    assert summary.total_invested == Decimal("200")
    assert summary.holdings[0].symbol == "TCS"
