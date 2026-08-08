from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import AssetType, Currency, Exchange, TradeStatus, TransactionType
from app.services.historical_holdings_service import (
    HistoricalHoldingsService,
    NaiveAsOfDatetimeError,
)
from app.services.position_accounting_service import OversellError


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")


def _build_trade(
    *,
    trade_id: UUID,
    timestamp: datetime,
    transaction_type: TransactionType,
    quantity: str,
    price: str,
    status: TradeStatus = TradeStatus.EXECUTED,
    symbol: str = "MSFT",
    exchange: Exchange = Exchange.NSE,
    asset_type: AssetType = AssetType.STOCK,
    currency: Currency = Currency.INR,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=trade_id,
        user_id=USER_A,
        asset_symbol=symbol,
        exchange=exchange,
        asset_type=asset_type,
        currency=currency,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        price_per_unit=Decimal(price),
        brokerage_fee=Decimal("0"),
        taxes=Decimal("0"),
        trade_timestamp=timestamp,
        status=status,
    )


def _build_service_with_trades(trades: list[SimpleNamespace]) -> tuple[HistoricalHoldingsService, Mock]:
    trade_repository = Mock()
    trade_repository.list_executed_up_to.return_value = trades
    service = HistoricalHoldingsService(trade_repository)
    return service, trade_repository


def test_no_trades_returns_empty_holdings() -> None:
    service, _ = _build_service_with_trades([])
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    assert service.get_holdings_as_of(user_id=USER_A, as_of=as_of) == []


def test_one_executed_buy_before_t_is_included() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trade = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000001"),
        timestamp=as_of - timedelta(minutes=10),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
    )

    service, _ = _build_service_with_trades([trade])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert len(holdings) == 1
    assert holdings[0].asset_symbol == "MSFT"
    assert holdings[0].remaining_quantity == Decimal("5")
    assert holdings[0].remaining_cost_basis == Decimal("500")


def test_buy_after_t_is_excluded() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trade = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000002"),
        timestamp=as_of + timedelta(seconds=1),
        transaction_type=TransactionType.BUY,
        quantity="2",
        price="100",
    )

    service, _ = _build_service_with_trades([trade])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert holdings == []


def test_executed_sell_before_t_is_reflected() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    buy = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000003"),
        timestamp=as_of - timedelta(hours=2),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
    )
    sell = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000004"),
        timestamp=as_of - timedelta(hours=1),
        transaction_type=TransactionType.SELL,
        quantity="2",
        price="120",
    )

    service, _ = _build_service_with_trades([buy, sell])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert len(holdings) == 1
    assert holdings[0].remaining_quantity == Decimal("3")
    assert holdings[0].remaining_cost_basis == Decimal("300")
    assert holdings[0].average_cost == Decimal("100")


def test_sell_after_t_is_excluded() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    buy = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000005"),
        timestamp=as_of - timedelta(hours=1),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
    )
    sell_after = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000006"),
        timestamp=as_of + timedelta(minutes=1),
        transaction_type=TransactionType.SELL,
        quantity="2",
        price="120",
    )

    service, _ = _build_service_with_trades([buy, sell_after])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert len(holdings) == 1
    assert holdings[0].remaining_quantity == Decimal("5")


def test_non_executed_trade_before_t_is_excluded() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    pending_buy = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000007"),
        timestamp=as_of - timedelta(minutes=30),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
        status=TradeStatus.PENDING,
    )

    service, _ = _build_service_with_trades([pending_buy])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert holdings == []


def test_multiple_trades_replay_deterministically() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trades = [
        _build_trade(
            trade_id=UUID("00000000-0000-0000-0000-000000000011"),
            timestamp=as_of - timedelta(hours=3),
            transaction_type=TransactionType.BUY,
            quantity="10",
            price="100",
        ),
        _build_trade(
            trade_id=UUID("00000000-0000-0000-0000-000000000012"),
            timestamp=as_of - timedelta(hours=2),
            transaction_type=TransactionType.BUY,
            quantity="5",
            price="200",
        ),
        _build_trade(
            trade_id=UUID("00000000-0000-0000-0000-000000000013"),
            timestamp=as_of - timedelta(hours=1),
            transaction_type=TransactionType.SELL,
            quantity="3",
            price="180",
        ),
    ]

    service, _ = _build_service_with_trades(trades)
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert len(holdings) == 1
    assert holdings[0].remaining_quantity == Decimal("12")
    assert holdings[0].remaining_cost_basis == Decimal("1600")
    assert holdings[0].average_cost == Decimal("133.3333333333333333333333333")


def test_same_timestamp_trades_are_ordered_by_trade_id() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    same_ts = as_of - timedelta(minutes=5)

    buy_first_by_id = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000020"),
        timestamp=same_ts,
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="100",
    )
    sell_second_by_id = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000021"),
        timestamp=same_ts,
        transaction_type=TransactionType.SELL,
        quantity="1",
        price="110",
    )

    service, _ = _build_service_with_trades([sell_second_by_id, buy_first_by_id])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of)

    assert holdings == []


def test_future_trade_cannot_affect_historical_holdings() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trade_a = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000030"),
        timestamp=t - timedelta(minutes=30),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
    )
    trade_b = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000031"),
        timestamp=t + timedelta(minutes=30),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="200",
    )

    current_position_simulation = {
        "remaining_quantity": Decimal("10"),
        "remaining_cost_basis": Decimal("1500"),
    }
    assert current_position_simulation["remaining_quantity"] == Decimal("10")

    service, _ = _build_service_with_trades([trade_a, trade_b])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=t)

    assert len(holdings) == 1
    assert holdings[0].remaining_quantity == Decimal("5")
    assert holdings[0].remaining_cost_basis == Decimal("500")


def test_current_position_state_is_not_used() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trade = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000040"),
        timestamp=t - timedelta(minutes=1),
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="100",
    )

    service, trade_repository = _build_service_with_trades([trade])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=t)

    trade_repository.list_executed_up_to.assert_called_once_with(user_id=USER_A, as_of=t)
    assert len(holdings) == 1


def test_naive_datetime_is_rejected() -> None:
    service, _ = _build_service_with_trades([])

    with pytest.raises(NaiveAsOfDatetimeError):
        service.get_holdings_as_of(
            user_id=USER_A,
            as_of=datetime(2026, 8, 8, 10, 0),
        )


def test_utc_aware_timestamp_works_correctly() -> None:
    as_of_utc = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    as_of_ist = datetime(2026, 8, 8, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    trade = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000050"),
        timestamp=as_of_utc - timedelta(minutes=1),
        transaction_type=TransactionType.BUY,
        quantity="1",
        price="100",
    )

    service, trade_repository = _build_service_with_trades([trade])
    holdings = service.get_holdings_as_of(user_id=USER_A, as_of=as_of_ist)

    called_as_of = trade_repository.list_executed_up_to.call_args.kwargs["as_of"]
    assert called_as_of == as_of_utc
    assert len(holdings) == 1


def test_oversell_history_failure_is_surfaced() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    invalid_sell = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000060"),
        timestamp=t - timedelta(minutes=1),
        transaction_type=TransactionType.SELL,
        quantity="2",
        price="100",
    )

    service, _ = _build_service_with_trades([invalid_sell])

    with pytest.raises(OversellError):
        service.get_holdings_as_of(user_id=USER_A, as_of=t)


def test_user_isolation_is_preserved() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, trade_repository = _build_service_with_trades([])

    service.get_holdings_as_of(user_id=USER_B, as_of=t)

    assert trade_repository.list_executed_up_to.call_args.kwargs["user_id"] == USER_B


def test_critical_no_hindsight_recommendation_time_boundary() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    trade_before_t = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000070"),
        timestamp=t - timedelta(minutes=15),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="100",
    )
    trade_after_t = _build_trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000071"),
        timestamp=t + timedelta(minutes=15),
        transaction_type=TransactionType.BUY,
        quantity="5",
        price="300",
    )

    current_position_including_future_trade = {
        "remaining_quantity": Decimal("10"),
        "remaining_cost_basis": Decimal("2000"),
    }
    assert current_position_including_future_trade["remaining_quantity"] == Decimal("10")

    service, _ = _build_service_with_trades([trade_before_t, trade_after_t])
    holdings_as_of_t = service.get_holdings_as_of(user_id=USER_A, as_of=t)

    assert len(holdings_as_of_t) == 1
    assert holdings_as_of_t[0].remaining_quantity == Decimal("5")
    assert holdings_as_of_t[0].remaining_cost_basis == Decimal("500")
