"""Orders, fills, rejections and the execution model (Feature 005, step 4).

`NextOpenExecution` fills at the bar's split-adjusted `open`, with zero cost; it is the only v1 model. It never reads
`adjusted_close`. Only the two business rejections (`InsufficientCash`, `InsufficientPosition`) become `Rejection`
records; every other error propagates. A rejection is whole: nothing is partially filled, resized or clamped.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.enums import TradeSide
from app.domain.instrument import Instrument
from app.quant.market_data.bar import MarketBar
from .portfolio import InsufficientCash, InsufficientPosition, Portfolio, _whole_shares

INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
UNFILLED_END_OF_DATA = "UNFILLED_END_OF_DATA"
REJECTION_REASONS = (INSUFFICIENT_CASH, INSUFFICIENT_POSITION, UNFILLED_END_OF_DATA)


@dataclass(frozen=True)
class Order:
    """A whole-share order decided on `decided_on` (after that session's close) for the next common session."""

    order_id: int
    decided_on: date
    instrument: Instrument
    side: TradeSide
    quantity: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.order_id, bool) or not isinstance(self.order_id, int) or self.order_id < 1:
            raise ValueError("order_id must be a positive int")
        if not isinstance(self.side, TradeSide):
            raise ValueError("side must be a TradeSide")
        _whole_shares("quantity", self.quantity)


@dataclass(frozen=True)
class Fill:
    order_id: int
    date: date
    instrument: Instrument
    side: TradeSide
    quantity: Decimal
    price: Decimal
    notional: Decimal


@dataclass(frozen=True)
class Rejection:
    order_id: int
    date: date  # the session on which the order was rejected (for UNFILLED_END_OF_DATA: the final session)
    reason: str

    def __post_init__(self) -> None:
        if self.reason not in REJECTION_REASONS:
            raise ValueError(f"unknown rejection reason {self.reason!r}")


class ExecutionModel(Protocol):
    def fill(self, order: Order, bar: MarketBar, portfolio: Portfolio) -> Fill | Rejection: ...


class NextOpenExecution:
    """Fill at `bar.open` (the bar of the settlement session), zero cost. The portfolio is only inspected here."""

    def fill(self, order: Order, bar: MarketBar, portfolio: Portfolio) -> Fill | Rejection:
        price = bar.open
        try:
            if order.side is TradeSide.BUY:
                after = portfolio.buy(order.instrument, order.quantity, price)
                notional = portfolio.cash - after.cash
            else:
                after = portfolio.sell(order.instrument, order.quantity, price)
                notional = after.cash - portfolio.cash
        except InsufficientCash:
            return Rejection(order.order_id, bar.session_date, INSUFFICIENT_CASH)
        except InsufficientPosition:
            return Rejection(order.order_id, bar.session_date, INSUFFICIENT_POSITION)
        return Fill(order.order_id, bar.session_date, order.instrument, order.side, order.quantity, price, notional)


def apply_fill(portfolio: Portfolio, fill: Fill) -> Portfolio:
    """The portfolio after `fill` (a new object)."""
    if fill.side is TradeSide.BUY:
        return portfolio.buy(fill.instrument, fill.quantity, fill.price)
    return portfolio.sell(fill.instrument, fill.quantity, fill.price)
