from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.models.enums import AssetType, Currency, Exchange, TradeStatus
from app.repositories.trade_repository import TradeRepository
from app.services.position_accounting_service import PositionAccountingService


@dataclass(frozen=True)
class HoldingAsOf:
    asset_symbol: str
    exchange: Exchange | None
    asset_type: AssetType | None
    currency: Currency
    remaining_quantity: Decimal
    remaining_cost_basis: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class _HoldingAccumulator:
    asset_symbol: str
    exchange: Exchange | None
    asset_type: AssetType | None
    currency: Currency
    remaining_quantity: Decimal
    remaining_cost_basis: Decimal
    average_cost: Decimal


class NaiveAsOfDatetimeError(ValueError):
    """Raised when an as_of datetime is provided without timezone information."""


class HistoricalHoldingsService:
    def __init__(self, trade_repository: TradeRepository):
        self.trade_repository = trade_repository

    def get_holdings_as_of(self, *, user_id: UUID, as_of: datetime) -> list[HoldingAsOf]:
        as_of_utc = self._normalize_as_of_to_utc(as_of)

        trades = self.trade_repository.list_executed_up_to(
            user_id=user_id,
            as_of=as_of_utc,
        )

        executed_trades = [
            trade
            for trade in trades
            if trade.status == TradeStatus.EXECUTED
            and trade.trade_timestamp <= as_of_utc
        ]
        ordered_trades = sorted(
            executed_trades,
            key=lambda trade: (trade.trade_timestamp, trade.id),
        )

        holdings: dict[tuple[str, Exchange | None, AssetType | None, Currency], _HoldingAccumulator] = {}

        for trade in ordered_trades:
            key = (trade.asset_symbol, trade.exchange, trade.asset_type, trade.currency)
            current = holdings.get(key)

            current_quantity = current.remaining_quantity if current is not None else Decimal("0")
            current_cost_basis = current.remaining_cost_basis if current is not None else Decimal("0")

            result = PositionAccountingService.apply_trade(
                current_quantity=current_quantity,
                current_cost_basis=current_cost_basis,
                transaction_type=trade.transaction_type,
                quantity=trade.quantity,
                price_per_unit=trade.price_per_unit,
                brokerage_fee=trade.brokerage_fee,
                taxes=trade.taxes,
            )

            holdings[key] = _HoldingAccumulator(
                asset_symbol=trade.asset_symbol,
                exchange=trade.exchange,
                asset_type=trade.asset_type,
                currency=trade.currency,
                remaining_quantity=result.remaining_quantity,
                remaining_cost_basis=result.remaining_cost_basis,
                average_cost=result.average_cost,
            )

        return [
            HoldingAsOf(
                asset_symbol=holding.asset_symbol,
                exchange=holding.exchange,
                asset_type=holding.asset_type,
                currency=holding.currency,
                remaining_quantity=holding.remaining_quantity,
                remaining_cost_basis=holding.remaining_cost_basis,
                average_cost=holding.average_cost,
            )
            for holding in holdings.values()
            if holding.remaining_quantity > 0
        ]

    @staticmethod
    def _normalize_as_of_to_utc(as_of: datetime) -> datetime:
        if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
            raise NaiveAsOfDatetimeError("as_of must be timezone-aware")

        return as_of.astimezone(timezone.utc)
