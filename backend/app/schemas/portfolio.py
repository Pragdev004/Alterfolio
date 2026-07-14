from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class HoldingSummary(BaseModel):
    symbol: str
    quantity: Decimal
    average_buy_price: Decimal
    invested_amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class PortfolioSummary(BaseModel):
    total_trades: int
    total_invested: Decimal
    holdings: list[HoldingSummary]

    model_config = ConfigDict(from_attributes=True)