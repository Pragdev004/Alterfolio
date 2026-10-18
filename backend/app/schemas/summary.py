from typing import Literal

from pydantic import computed_field

from app.domain.enums import Currency, Exchange
from app.schemas.display import WithDisplay
from app.schemas.trade import HoldingOut, MoneyOut, PriceOut, WhenOut


_QUOTE_WHY = {
    "STALE": "The latest price for this listing is too old to use.",
    "NOT_FOUND": "No price was found for this listing.",
    "PROVIDER_ERROR": "The price source did not answer.",
    "INVALID": "The price source returned an unusable price.",
}


_COST_BASIS_WHY = (
    "Cost basis is incomplete: brokerage and taxes are unknown for imported buys, "
    "so profit and loss cannot be stated exactly."
)


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
        why = _QUOTE_WHY.get(self.quote_status, "No valuation is available for this holding.")
        if self.quote_status == "VALUED" and not self.cost_basis_complete:
            return {"market_value": why, "unrealized_pnl": _COST_BASIS_WHY}
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
        why = f"Only {self.valued_holdings_count} of {self.holdings_count} holdings could be priced."
        pnl = _COST_BASIS_WHY if self.valued_holdings_count and not self.cost_basis_complete else why
        return {"total_market_value": why, "total_unrealized_pnl": pnl}

    def display_notes(self) -> dict[str, str]:
        if self.valuation_status != "PARTIAL":
            return {}
        note = f" (partial: {self.valued_holdings_count} of {self.holdings_count} holdings valued)"
        return {"total_market_value": note, "total_unrealized_pnl": note}

    @computed_field
    @property
    def valuation_text(self) -> str:
        return f"{self.valued_holdings_count} of {self.holdings_count} holdings valued"

    @computed_field
    @property
    def incomplete_cost_basis_count(self) -> int:
        return sum(1 for h in self.holdings if not h.cost_basis_complete)

    @computed_field
    @property
    def status_label(self) -> str:
        """The chip text: COMPLETE only when every holding is priced AND every cost basis is complete."""
        if self.valuation_status != "COMPLETE":
            return self.valuation_status
        return "COMPLETE" if self.cost_basis_complete else "PARTIAL"

    @computed_field
    @property
    def status_text(self) -> str:
        """One sentence behind the chip: what was valued, and what is missing from the cost basis."""
        if self.holdings_count == 0:
            return ""
        if self.cost_basis_complete:
            return self.valuation_text
        n = self.incomplete_cost_basis_count
        noun = "holding" if n == 1 else "holdings"
        return f"{self.valuation_text}. Cost basis is incomplete for {n} of {self.holdings_count} {noun}, so profit and loss is not shown."
