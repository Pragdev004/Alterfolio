from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HoldingSummary(BaseModel):
    symbol: str
    quantity: Decimal
    average_buy_price: Decimal
    invested_amount: Decimal

    exchange: str | None = None
    asset_type: str | None = None
    currency: str | None = None

    current_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealized_profit_loss: Decimal | None = None
    realized_profit_loss: Decimal = Decimal("0")
    quote_status: Literal["AVAILABLE", "UNAVAILABLE"] = "UNAVAILABLE"

    model_config = ConfigDict(from_attributes=True)


class PortfolioSummary(BaseModel):
    total_trades: int
    total_invested: Decimal
    total_market_value: Decimal | None = None
    total_unrealized_profit_loss: Decimal | None = None
    total_realized_profit_loss: Decimal = Decimal("0")
    valuation_status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"
    valued_at: datetime | None = None
    holdings: list[HoldingSummary]

    model_config = ConfigDict(from_attributes=True)