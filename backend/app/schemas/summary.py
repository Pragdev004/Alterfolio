from typing import Literal

from pydantic import computed_field

from app.domain.enums import Currency, Exchange
from app.schemas.display import WithDisplay
from app.schemas.trade import HoldingOut, MoneyOut, PriceOut, WhenOut


class QuoteOut(WithDisplay):
    symbol: str
    exchange: Exchange
    price: PriceOut
    currency: Currency
    price_timestamp: WhenOut
    retrieved_at: WhenOut
    source: str


class SummaryHoldingOut(HoldingOut):
    quote_status: Literal["VALUED", "STALE", "NOT_FOUND", "PROVIDER_ERROR", "INVALID"]
    quote: QuoteOut | None
    market_value: MoneyOut | None
    unrealized_pnl: MoneyOut | None

    def unavailable_reasons(self) -> dict[str, str]:
        why = f"no valuation: quote status {self.quote_status}"
        return {"market_value": why, "unrealized_pnl": why}


class SummaryOut(WithDisplay):
    schema_version: Literal[1] = 1
    basis: Literal["CURRENT"] = "CURRENT"
    valuation_time: WhenOut
    valuation_status: Literal["COMPLETE", "PARTIAL", "UNAVAILABLE"]
    total_trades: int
    holdings_count: int
    valued_holdings_count: int
    total_invested: MoneyOut
    total_market_value: MoneyOut | None
    total_unrealized_pnl: MoneyOut | None
    cost_basis_complete: bool
    holdings: list[SummaryHoldingOut]

    def unavailable_reasons(self) -> dict[str, str]:
        why = f"portfolio valuation is {self.valuation_status}: {self.valued_holdings_count} of {self.holdings_count} holdings valued"
        return {"total_market_value": why, "total_unrealized_pnl": why}

    def display_notes(self) -> dict[str, str]:
        if self.valuation_status != "PARTIAL":
            return {}
        note = f" (partial: {self.valued_holdings_count} of {self.holdings_count} holdings valued)"
        return {"total_market_value": note, "total_unrealized_pnl": note}

    @computed_field
    @property
    def valuation_text(self) -> str:
        return f"{self.valued_holdings_count} of {self.holdings_count} holdings valued"
