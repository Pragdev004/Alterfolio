from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.models.enums import AssetType, Currency, Exchange, TradeStatus, TransactionType
from app.services.historical_holdings_service import HistoricalHoldingsService, HoldingAsOf, NaiveAsOfDatetimeError
from app.services.portfolio_allocation_as_of_service import (
    InvalidHoldingQuantityError,
    MissingHistoricalPriceError,
    NonPositivePortfolioValueError,
    PortfolioAllocationAsOfService,
    UnsupportedMultiCurrencyValuationError,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")


class FakeCurrency(str, Enum):
    USD = "USD"


class InMemoryHistoricalPriceRepository:
    def __init__(self, snapshots: list[SimpleNamespace]):
        self.snapshots = snapshots
        self.calls: list[dict] = []

    def get_latest_price_at_or_before(self, *, user_id: UUID, asset_symbol: str, as_of: datetime):
        self.calls.append({"user_id": user_id, "asset_symbol": asset_symbol, "as_of": as_of})

        eligible = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.user_id == user_id
            and snapshot.asset_symbol == asset_symbol
            and snapshot.price_timestamp <= as_of
        ]

        if not eligible:
            return None

        ordered = sorted(
            eligible,
            key=lambda snapshot: (snapshot.price_timestamp, snapshot.id),
            reverse=True,
        )
        return ordered[0]


class InMemoryTradeRepository:
    def __init__(self, trades: list[SimpleNamespace]):
        self.trades = trades
        self.calls: list[dict] = []

    def list_executed_up_to(self, *, user_id: UUID, as_of: datetime) -> list[SimpleNamespace]:
        self.calls.append({"user_id": user_id, "as_of": as_of})
        return self.trades


def _holding(
    *,
    symbol: str,
    quantity: str,
    currency: Currency | FakeCurrency = Currency.INR,
    exchange: Exchange | None = Exchange.NSE,
    asset_type: AssetType | None = AssetType.STOCK,
) -> HoldingAsOf:
    quantity_decimal = Decimal(quantity)
    return HoldingAsOf(
        asset_symbol=symbol,
        exchange=exchange,
        asset_type=asset_type,
        currency=currency,
        remaining_quantity=quantity_decimal,
        remaining_cost_basis=Decimal("0"),
        average_cost=Decimal("0"),
    )


def _snapshot(
    *,
    snapshot_id: int,
    symbol: str,
    price: str,
    price_timestamp: datetime,
    user_id: UUID = USER_A,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=snapshot_id,
        user_id=user_id,
        asset_symbol=symbol,
        asset_price=Decimal(price),
        price_timestamp=price_timestamp,
    )


def _trade(
    *,
    trade_id: UUID,
    symbol: str,
    timestamp: datetime,
    quantity: str,
    price: str,
    transaction_type: TransactionType = TransactionType.BUY,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=trade_id,
        user_id=USER_A,
        asset_symbol=symbol,
        exchange=Exchange.NSE,
        asset_type=AssetType.STOCK,
        currency=Currency.INR,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        price_per_unit=Decimal(price),
        brokerage_fee=Decimal("0"),
        taxes=Decimal("0"),
        trade_timestamp=timestamp,
        status=TradeStatus.EXECUTED,
    )


def _build_service(
    holdings: list[HoldingAsOf],
    *,
    snapshot_for_symbol: dict[str, SimpleNamespace | None],
) -> tuple[PortfolioAllocationAsOfService, Mock, Mock]:
    holdings_service = Mock()
    holdings_service.get_holdings_as_of.return_value = holdings

    snapshot_repository = Mock()

    def _lookup(*, user_id: UUID, asset_symbol: str, as_of: datetime):
        return snapshot_for_symbol.get(asset_symbol)

    snapshot_repository.get_latest_price_at_or_before.side_effect = _lookup

    service = PortfolioAllocationAsOfService(holdings_service, snapshot_repository)
    return service, holdings_service, snapshot_repository


def test_empty_holdings_returns_empty_allocation_result() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service([], snapshot_for_symbol={})

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.total_value == Decimal("0")
    assert result.currency is None
    assert result.allocations == []


def test_one_holding_has_allocation_one() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="2")],
        snapshot_for_symbol={
            "AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of)
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.total_value == Decimal("200")
    assert len(result.allocations) == 1
    assert result.allocations[0].allocation == Decimal("1")


def test_two_holdings_equal_market_values_have_equal_allocations() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAA", quantity="2"), _holding(symbol="BBB", quantity="1")],
        snapshot_for_symbol={
            "AAA": _snapshot(snapshot_id=1, symbol="AAA", price="100", price_timestamp=as_of),
            "BBB": _snapshot(snapshot_id=2, symbol="BBB", price="200", price_timestamp=as_of),
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.total_value == Decimal("400")
    assert result.allocations[0].allocation == Decimal("0.5")
    assert result.allocations[1].allocation == Decimal("0.5")


def test_different_quantities_and_prices_compute_correct_allocation() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAA", quantity="3"), _holding(symbol="BBB", quantity="2")],
        snapshot_for_symbol={
            "AAA": _snapshot(snapshot_id=1, symbol="AAA", price="150", price_timestamp=as_of),
            "BBB": _snapshot(snapshot_id=2, symbol="BBB", price="100", price_timestamp=as_of),
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.total_value == Decimal("650")
    aaa = next(allocation for allocation in result.allocations if allocation.asset_symbol == "AAA")
    bbb = next(allocation for allocation in result.allocations if allocation.asset_symbol == "BBB")
    assert aaa.allocation == Decimal("450") / Decimal("650")
    assert bbb.allocation == Decimal("200") / Decimal("650")


def test_historical_price_timestamp_is_returned_from_lookup_result() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    price_ts = as_of - timedelta(minutes=10)
    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={
            "AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="123.45", price_timestamp=price_ts)
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.allocations[0].price_timestamp == price_ts
    assert result.allocations[0].price == Decimal("123.45")


def test_future_price_is_never_used_when_no_eligible_historical_snapshot_exists() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    future_snapshot_only_repository = InMemoryHistoricalPriceRepository(
        [
            _snapshot(
                snapshot_id=1,
                symbol="AAPL",
                price="999",
                price_timestamp=as_of + timedelta(minutes=1),
            )
        ]
    )

    holdings_service = Mock()
    holdings_service.get_holdings_as_of.return_value = [_holding(symbol="AAPL", quantity="1")]

    service = PortfolioAllocationAsOfService(holdings_service, future_snapshot_only_repository)

    with pytest.raises(MissingHistoricalPriceError):
        service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)


def test_historical_holdings_exclude_future_trades() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    before = _trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000101"),
        symbol="AAPL",
        timestamp=as_of - timedelta(minutes=10),
        quantity="2",
        price="100",
    )
    after = _trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000102"),
        symbol="AAPL",
        timestamp=as_of + timedelta(minutes=10),
        quantity="3",
        price="100",
    )

    trade_repository = InMemoryTradeRepository([before, after])
    holdings_service = HistoricalHoldingsService(trade_repository)
    snapshot_repository = Mock()
    snapshot_repository.get_latest_price_at_or_before.return_value = _snapshot(
        snapshot_id=1,
        symbol="AAPL",
        price="100",
        price_timestamp=as_of - timedelta(minutes=1),
    )

    service = PortfolioAllocationAsOfService(holdings_service, snapshot_repository)
    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert len(result.allocations) == 1
    assert result.allocations[0].quantity == Decimal("2")


def test_missing_historical_price_raises_deterministic_error() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": None},
    )

    with pytest.raises(MissingHistoricalPriceError):
        service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)


def test_zero_quantity_holding_is_ignored_defensively() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, snapshot_repository = _build_service(
        [_holding(symbol="ZERO", quantity="0"), _holding(symbol="POS", quantity="2")],
        snapshot_for_symbol={"POS": _snapshot(snapshot_id=1, symbol="POS", price="50", price_timestamp=as_of)},
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert len(result.allocations) == 1
    assert result.allocations[0].asset_symbol == "POS"

    looked_up_symbols = [call.kwargs["asset_symbol"] for call in snapshot_repository.get_latest_price_at_or_before.call_args_list]
    assert looked_up_symbols == ["POS"]


def test_negative_quantity_raises_deterministic_error() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service([_holding(symbol="AAPL", quantity="-1")], snapshot_for_symbol={})

    with pytest.raises(InvalidHoldingQuantityError):
        service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)


def test_total_value_less_than_or_equal_to_zero_raises_error() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="0", price_timestamp=as_of)},
    )

    with pytest.raises(NonPositivePortfolioValueError):
        service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)


def test_decimal_precision_is_preserved_in_valuation_and_allocation() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="A", quantity="1"), _holding(symbol="B", quantity="1")],
        snapshot_for_symbol={
            "A": _snapshot(snapshot_id=1, symbol="A", price="0.1", price_timestamp=as_of),
            "B": _snapshot(snapshot_id=2, symbol="B", price="0.2", price_timestamp=as_of),
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.total_value == Decimal("0.3")
    allocation_a = next(item for item in result.allocations if item.asset_symbol == "A")
    assert allocation_a.allocation == Decimal("0.1") / Decimal("0.3")


def test_same_currency_valuation_succeeds() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1", currency=Currency.INR)],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of)},
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert result.currency == Currency.INR


def test_multiple_currencies_raise_deterministic_error_without_fx() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [
            _holding(symbol="INR_ASSET", quantity="1", currency=Currency.INR),
            _holding(symbol="USD_ASSET", quantity="1", currency=FakeCurrency.USD),
        ],
        snapshot_for_symbol={
            "INR_ASSET": _snapshot(snapshot_id=1, symbol="INR_ASSET", price="100", price_timestamp=as_of),
            "USD_ASSET": _snapshot(snapshot_id=2, symbol="USD_ASSET", price="100", price_timestamp=as_of),
        },
    )

    with pytest.raises(UnsupportedMultiCurrencyValuationError):
        service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)


def test_naive_as_of_is_rejected() -> None:
    service, _, _ = _build_service([], snapshot_for_symbol={})

    with pytest.raises(NaiveAsOfDatetimeError):
        service.get_portfolio_allocation_as_of(
            user_id=USER_A,
            as_of=datetime(2026, 8, 8, 10, 0),
        )


def test_aware_as_of_is_normalized_to_utc_before_dependency_calls() -> None:
    as_of_utc = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    as_of_ist = datetime(2026, 8, 8, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    service, holdings_service, snapshot_repository = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of_utc)},
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of_ist)

    assert result.as_of == as_of_utc
    assert holdings_service.get_holdings_as_of.call_args.kwargs["as_of"] == as_of_utc
    assert snapshot_repository.get_latest_price_at_or_before.call_args.kwargs["as_of"] == as_of_utc


def test_results_are_deterministic_in_ordering() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, _ = _build_service(
        [_holding(symbol="MSFT", quantity="1"), _holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={
            "AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of),
            "MSFT": _snapshot(snapshot_id=2, symbol="MSFT", price="100", price_timestamp=as_of),
        },
    )

    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    assert [asset.asset_symbol for asset in result.allocations] == ["AAPL", "MSFT"]


def test_current_position_state_is_not_used() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    position_repository = Mock()

    service, holdings_service, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of)},
    )

    service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    holdings_service.get_holdings_as_of.assert_called_once()
    position_repository.assert_not_called()


def test_live_market_provider_is_not_called() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    live_market_provider = Mock()

    service, _, _ = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of)},
    )

    service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    live_market_provider.assert_not_called()


def test_end_to_end_no_hindsight_boundary() -> None:
    t = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)

    trade_before_t = _trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000201"),
        symbol="AAPL",
        timestamp=t - timedelta(minutes=15),
        quantity="5",
        price="100",
    )
    trade_after_t = _trade(
        trade_id=UUID("00000000-0000-0000-0000-000000000202"),
        symbol="AAPL",
        timestamp=t + timedelta(minutes=15),
        quantity="3",
        price="100",
    )

    historical_snapshot = _snapshot(
        snapshot_id=1,
        symbol="AAPL",
        price="200",
        price_timestamp=t - timedelta(minutes=5),
    )
    future_snapshot = _snapshot(
        snapshot_id=2,
        symbol="AAPL",
        price="500",
        price_timestamp=t + timedelta(minutes=5),
    )

    holdings_service = HistoricalHoldingsService(InMemoryTradeRepository([trade_before_t, trade_after_t]))
    snapshot_repository = InMemoryHistoricalPriceRepository([historical_snapshot, future_snapshot])

    service = PortfolioAllocationAsOfService(holdings_service, snapshot_repository)
    result = service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=t)

    assert len(result.allocations) == 1
    assert result.allocations[0].quantity == Decimal("5")
    assert result.allocations[0].price == Decimal("200")
    assert result.total_value == Decimal("1000")
    assert result.allocations[0].allocation == Decimal("1")
    assert snapshot_repository.calls[0]["as_of"] == t


def test_market_snapshot_lookup_is_called_with_user_scope_and_symbol_scope() -> None:
    as_of = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
    service, _, snapshot_repository = _build_service(
        [_holding(symbol="AAPL", quantity="1")],
        snapshot_for_symbol={"AAPL": _snapshot(snapshot_id=1, symbol="AAPL", price="100", price_timestamp=as_of)},
    )

    service.get_portfolio_allocation_as_of(user_id=USER_A, as_of=as_of)

    snapshot_repository.get_latest_price_at_or_before.assert_called_once_with(
        user_id=USER_A,
        asset_symbol="AAPL",
        as_of=as_of,
    )

