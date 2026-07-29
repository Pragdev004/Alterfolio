from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    AssetType,
    Currency,
    Exchange,
    InvestmentHorizon,
    MarketSession,
    TradeSource,
    TradeStatus,
    TransactionType,
)


class TradeBase(BaseModel):
    asset_symbol: str
    asset_name: str
    asset_type: AssetType
    exchange: Exchange
    currency: Currency = Currency.INR

    transaction_type: TransactionType
    quantity: Decimal
    price_per_unit: Decimal
    trade_timestamp: datetime

    brokerage_fee: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")

    broker: str | None = None
    order_id: str | None = None

    trade_source: TradeSource
    market_session: MarketSession
    status: TradeStatus = TradeStatus.EXECUTED

    investment_horizon: InvestmentHorizon | None = None
    notes: str | None = None


class TradeCreate(TradeBase):
    user_id: UUID | None = None



class TradeUpdate(BaseModel):
    broker: str | None = None
    order_id: str | None = None
    notes: str | None = None
    status: TradeStatus | None = None


class TradeResponse(TradeBase):
    id: UUID
    user_id: UUID

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)