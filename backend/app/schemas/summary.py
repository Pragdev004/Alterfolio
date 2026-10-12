from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.enums import Currency, Exchange
from app.schemas.trade import DecimalOut, HoldingOut


class QuoteOut(BaseModel):
    symbol: str
    exchange: Exchange
    price: DecimalOut
    currency: Currency
    price_timestamp: datetime
    retrieved_at: datetime
    source: str


class SummaryHoldingOut(HoldingOut):
    quote_status: Literal["VALUED", "STALE", "NOT_FOUND", "PROVIDER_ERROR", "INVALID"]
    quote: QuoteOut | None
    market_value: DecimalOut | None
    unrealized_pnl: DecimalOut | None


class SummaryOut(BaseModel):
    schema_version: Literal[1] = 1
    basis: Literal["CURRENT"] = "CURRENT"
    valuation_time: datetime
    valuation_status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    total_trades: int
    holdings_count: int
    valued_holdings_count: int
    total_invested: DecimalOut
    total_market_value: DecimalOut | None
    total_unrealized_pnl: DecimalOut | None
    cost_basis_complete: bool
    holdings: list[SummaryHoldingOut]
