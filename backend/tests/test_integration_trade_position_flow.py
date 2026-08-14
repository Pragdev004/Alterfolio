from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import app.models.position  # noqa: F401
import app.models.trade  # noqa: F401
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.position_repository import PositionRepository
from app.repositories.trade_repository import TradeRepository
from app.schemas.trade import TradeCreate
from app.services.market_service import MarketService
from app.services.portfolio_service import PortfolioService
from app.services.position_accounting_service import OversellError
from app.services.trade_service import TradeService


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _build_trade_payload(*, transaction_type: TransactionType, quantity: str, price: str) -> TradeCreate:
    return TradeCreate(
        user_id=USER_ID,
        asset_symbol="TCS",
        asset_name="Tata Consultancy Services",
        asset_type=AssetType.STOCK,
        exchange=Exchange.NSE,
        currency=Currency.INR,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        price_per_unit=Decimal(price),
        trade_timestamp=datetime.now(timezone.utc),
        brokerage_fee=Decimal("0"),
        taxes=Decimal("0"),
        trade_source=TradeSource.MANUAL,
        market_session=MarketSession.REGULAR,
        status=TradeStatus.EXECUTED,
    )


def _build_created_trade(trade: TradeCreate) -> SimpleNamespace:
    payload = trade.model_dump(exclude={"user_id"})
    return SimpleNamespace(user_id=USER_ID, **payload)


def _build_service() -> tuple[TradeService, Mock, Mock, Mock]:
    db = Mock()
    trade_repository = Mock()
    position_repository = Mock()

    service = TradeService(
        db=db,
        trade_repository=trade_repository,
        position_repository=position_repository,
    )
    return service, db, trade_repository, position_repository


class _StubMarketService(MarketService):
    def __init__(self, quotes: dict[str, dict[str, str]]):
        self._quotes = quotes

    def get_stock_quote(self, symbol: str):
        quote = self._quotes.get(symbol)
        if quote is None:
            raise RuntimeError("quote unavailable")

        return SimpleNamespace(
            symbol=quote["symbol"],
            currency=quote["currency"],
            current_price=quote["current_price"],
        )


def _build_real_services() -> tuple[TradeService, PortfolioService, Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    db = session_factory()
    trade_repository = TradeRepository(db)
    position_repository = PositionRepository(db)

    trade_service = TradeService(
        db=db,
        trade_repository=trade_repository,
        position_repository=position_repository,
    )
    portfolio_service = PortfolioService(
        portfolio_repository=PortfolioRepository(db),
        position_repository=position_repository,
        market_service=_StubMarketService(
            quotes={
                "TCS.NS": {"symbol": "TCS.NS", "currency": "INR", "current_price": "125"},
                "INFY.NS": {"symbol": "INFY.NS", "currency": "INR", "current_price": "210"},
            }
        ),
    )

    return trade_service, portfolio_service, db


def test_executed_buy_creates_trade_and_updates_position_in_single_transaction() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="150",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("2"),
        remaining_cost_basis=Decimal("200"),
        cumulative_realized_profit_loss=Decimal("10"),
    )
    position_repository.lock_position.return_value = existing_position

    service.create_trade(trade, USER_ID)

    trade_repository.create.assert_called_once()
    normalized_trade_arg = trade_repository.create.call_args.args[0]
    assert normalized_trade_arg.asset_symbol == "TCS"
    assert trade_repository.create.call_args.args[1] == USER_ID
    position_repository.lock_position.assert_called_once()
    position_repository.upsert_position.assert_called_once()

    upsert_kwargs = position_repository.upsert_position.call_args.kwargs
    assert upsert_kwargs["remaining_quantity"] == Decimal("3")
    assert upsert_kwargs["remaining_cost_basis"] == Decimal("350")
    assert upsert_kwargs["average_cost"] == Decimal("350") / Decimal("3")
    assert upsert_kwargs["cumulative_realized_profit_loss"] == Decimal("10")

    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_executed_sell_updates_position_and_realized_pl_in_single_transaction() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.SELL,
        quantity="4",
        price="120",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("10"),
        remaining_cost_basis=Decimal("1000"),
        cumulative_realized_profit_loss=Decimal("50"),
    )
    position_repository.lock_position.return_value = existing_position

    service.create_trade(trade, USER_ID)

    upsert_kwargs = position_repository.upsert_position.call_args.kwargs
    assert upsert_kwargs["remaining_quantity"] == Decimal("6")
    assert upsert_kwargs["remaining_cost_basis"] == Decimal("600")
    assert upsert_kwargs["average_cost"] == Decimal("100")
    assert upsert_kwargs["cumulative_realized_profit_loss"] == Decimal("130")

    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_trade_symbol_is_canonicalized_before_persistence_and_position_matching() -> None:
    service, _, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="100",
    ).model_copy(update={"asset_symbol": "tcs.ns"})

    created_trade = _build_created_trade(trade.model_copy(update={"asset_symbol": "TCS"}))
    trade_repository.create.return_value = created_trade
    position_repository.lock_position.return_value = None

    service.create_trade(trade, USER_ID)

    normalized_trade_arg = trade_repository.create.call_args.args[0]
    assert normalized_trade_arg.asset_symbol == "TCS"

    lock_kwargs = position_repository.lock_position.call_args.kwargs
    assert lock_kwargs["asset_symbol"] == "TCS"

    upsert_kwargs = position_repository.upsert_position.call_args.kwargs
    assert upsert_kwargs["asset_symbol"] == "TCS"


def test_trade_symbol_canonicalization_does_not_strip_non_exchange_period_suffix() -> None:
    service, _, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="100",
    ).model_copy(update={"asset_symbol": "brk.b"})

    created_trade = _build_created_trade(trade.model_copy(update={"asset_symbol": "BRK.B"}))
    trade_repository.create.return_value = created_trade
    position_repository.lock_position.return_value = None

    service.create_trade(trade, USER_ID)

    normalized_trade_arg = trade_repository.create.call_args.args[0]
    assert normalized_trade_arg.asset_symbol == "BRK.B"


def test_executed_sell_oversell_rolls_back_trade_and_position_updates() -> None:
    service, db, trade_repository, position_repository = _build_service()

    trade = _build_trade_payload(
        transaction_type=TransactionType.SELL,
        quantity="6",
        price="120",
    )
    created_trade = _build_created_trade(trade)
    trade_repository.create.return_value = created_trade

    existing_position = SimpleNamespace(
        remaining_quantity=Decimal("5"),
        remaining_cost_basis=Decimal("500"),
        cumulative_realized_profit_loss=Decimal("50"),
    )
    position_repository.lock_position.return_value = existing_position

    with pytest.raises(OversellError):
        service.create_trade(trade, USER_ID)

    position_repository.upsert_position.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_real_trade_to_position_to_summary_flow_with_user_isolation() -> None:
    trade_service, portfolio_service, db = _build_real_services()

    buy_a = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="10",
        price="100",
    )
    buy_b = _build_trade_payload(
        transaction_type=TransactionType.BUY,
        quantity="2",
        price="200",
    ).model_copy(update={"asset_symbol": "INFY", "asset_name": "Infosys"})

    try:
        trade_service.create_trade(buy_a, USER_A)
        trade_service.create_trade(buy_b, USER_B)

        summary_a_after_buy = portfolio_service.get_summary(USER_A)
        assert summary_a_after_buy.valuation_status == "COMPLETE"
        assert len(summary_a_after_buy.holdings) == 1
        assert summary_a_after_buy.holdings[0].symbol == "TCS"
        assert summary_a_after_buy.holdings[0].quantity == Decimal("10")
        assert summary_a_after_buy.holdings[0].invested_amount == Decimal("1000")

        summary_b_after_buy = portfolio_service.get_summary(USER_B)
        assert summary_b_after_buy.valuation_status == "COMPLETE"
        assert len(summary_b_after_buy.holdings) == 1
        assert summary_b_after_buy.holdings[0].symbol == "INFY"

        partial_sell_a = _build_trade_payload(
            transaction_type=TransactionType.SELL,
            quantity="4",
            price="130",
        )
        trade_service.create_trade(partial_sell_a, USER_A)

        summary_a_after_partial_sell = portfolio_service.get_summary(USER_A)
        assert summary_a_after_partial_sell.valuation_status == "COMPLETE"
        assert len(summary_a_after_partial_sell.holdings) == 1
        assert summary_a_after_partial_sell.holdings[0].quantity == Decimal("6")
        assert summary_a_after_partial_sell.holdings[0].invested_amount == Decimal("600")
        assert summary_a_after_partial_sell.holdings[0].realized_profit_loss == Decimal("120")
        assert summary_a_after_partial_sell.total_realized_profit_loss == Decimal("120")

        complete_sell_a = _build_trade_payload(
            transaction_type=TransactionType.SELL,
            quantity="6",
            price="140",
        )
        trade_service.create_trade(complete_sell_a, USER_A)

        summary_a_after_complete_sell = portfolio_service.get_summary(USER_A)
        assert summary_a_after_complete_sell.valuation_status == "UNAVAILABLE"
        assert summary_a_after_complete_sell.holdings == []
        assert summary_a_after_complete_sell.total_realized_profit_loss == Decimal("360")

        summary_b_after_all = portfolio_service.get_summary(USER_B)
        assert summary_b_after_all.valuation_status == "COMPLETE"
        assert len(summary_b_after_all.holdings) == 1
        assert summary_b_after_all.holdings[0].symbol == "INFY"
    finally:
        db.close()
