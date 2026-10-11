from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

from app.domain.enums import (
    AssetType,
    Currency,
    Exchange,
    MarketSession,
    TradeSide,
    TradeSource,
    TradeStatus,
)
from app.domain.numeric import MONEY_CONTEXT, SCALE

_QUANTUM = Decimal(1).scaleb(-SCALE)


def _parse_decimal(value: object) -> Decimal:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("decimal values must be JSON strings")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError("not a decimal number") from None


def money_str(value: Decimal) -> str:
    """Quantize once at the response boundary (half-even) and render as a plain string."""
    return format(MONEY_CONTEXT.quantize(value, _QUANTUM), "f")


DecimalIn = Annotated[Decimal, Field(allow_inf_nan=True), BeforeValidator(_parse_decimal)]
DecimalOut = Annotated[Decimal, PlainSerializer(money_str, return_type=str, when_used="always")]


class TradeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str
    asset_type: AssetType
    exchange: Exchange
    side: TradeSide
    quantity: DecimalIn
    price_per_unit: DecimalIn
    trade_timestamp: datetime
    market_session: MarketSession
    currency: Currency = Currency.INR
    brokerage_fee: DecimalIn = Decimal(0)
    taxes: DecimalIn = Decimal(0)
    status: TradeStatus = TradeStatus.EXECUTED
    broker: str | None = None
    broker_trade_id: str | None = None
    order_id: str | None = None
    notes: str | None = None


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    name: str
    asset_type: AssetType
    exchange: Exchange
    currency: Currency
    side: TradeSide
    quantity: DecimalOut
    price_per_unit: DecimalOut
    brokerage_fee: DecimalOut
    taxes: DecimalOut
    trade_timestamp: datetime
    recorded_at: datetime
    broker: str | None
    broker_trade_id: str | None
    order_id: str | None
    supersedes_trade_id: UUID | None
    source: TradeSource
    market_session: MarketSession
    status: TradeStatus
    notes: str | None


class HoldingOut(BaseModel):
    symbol: str
    exchange: Exchange
    quantity: DecimalOut
    average_buy_price: DecimalOut
    invested_amount: DecimalOut
