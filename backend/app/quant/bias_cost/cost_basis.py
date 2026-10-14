"""Weighted-average position fold per LISTING (spec sections 3, 4): sells with gross P&L, round trips, sell-day snapshots.

Cost basis is price-only (fees excluded) so gross P&L never depends on charge knownness; fees are attributed separately
and once, in overtrading. The method (weighted average) matches `services/holdings.py`. Derived values use `CALC_CONTEXT`.

A round trip is flat -> open -> flat on one listing. A sell on a listing with no earlier buy in the supplied trades is
excluded as opened before the window; a sell above the held quantity of a listing that did have buys is an input error.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.enums import TradeSide
from app.domain.instrument import Instrument

from .context import CALC_CONTEXT as C
from .errors import BiasInputError
from .types import BiasExclusion, LedgerTrade
from .validation import ValidatedBiasInputs, listing_name

ZERO = Decimal(0)


@dataclass(frozen=True)
class SellEvent:
    trade: LedgerTrade
    session: date
    gross_pnl: Decimal  # quantity * (price - average cost), price-only
    open_session: date
    open_index: int
    holding_sessions: int  # bar index of this sell minus bar index of the round trip's first buy


@dataclass(frozen=True)
class RoundTrip:
    instrument: Instrument
    open_session: date
    close_session: date
    holding_sessions: int
    gross_pnl: Decimal
    trades: tuple[LedgerTrade, ...]  # every buy and sell of the round trip, in order


@dataclass(frozen=True)
class PaperPosition:
    instrument: Instrument
    quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class SellDay:
    session: date
    realised: tuple[tuple[Instrument, Decimal], ...]  # per listing sold that day: summed gross P&L
    paper: tuple[PaperPosition, ...]  # listings held at the end of the day and NOT sold that day


@dataclass(frozen=True)
class FoldResult:
    sells: tuple[SellEvent, ...]
    round_trips: tuple[RoundTrip, ...]
    sell_days: tuple[SellDay, ...]
    exclusions: tuple[BiasExclusion, ...]


class _State:
    __slots__ = ("quantity", "cost", "ever_bought", "open_session", "open_index", "trades", "pnl")

    def __init__(self) -> None:
        self.quantity = ZERO
        self.cost = ZERO
        self.ever_bought = False
        self.open_session: date | None = None
        self.open_index = 0
        self.trades: list[LedgerTrade] = []
        self.pnl = ZERO


def fold_positions(inputs: ValidatedBiasInputs) -> FoldResult:
    sessions = dict(inputs.sessions)
    indexes = dict(inputs.indexes)
    states: dict[Instrument, _State] = {}
    sells: list[SellEvent] = []
    trips: list[RoundTrip] = []
    days: list[SellDay] = []
    exclusions: list[BiasExclusion] = []
    day: date | None = None
    sold_today: dict[Instrument, Decimal] = {}

    def close_day() -> None:
        if day is None or not sold_today:
            return
        paper = tuple(
            PaperPosition(i, s.quantity, C.divide(s.cost, s.quantity))
            for i, s in sorted(states.items(), key=lambda kv: (kv[0].symbol, kv[0].exchange.value))
            if s.quantity > 0 and i not in sold_today
        )
        realised = tuple(sorted(sold_today.items(), key=lambda kv: (kv[0].symbol, kv[0].exchange.value)))
        days.append(SellDay(day, realised, paper))

    for trade in inputs.trades:
        session = sessions[trade.trade_id]
        if day is not None and session < day:
            raise BiasInputError("session dates must not go backwards across listings")
        if session != day:
            close_day()
            day, sold_today = session, {}
        state = states.setdefault(trade.instrument, _State())
        index = indexes[trade.instrument]
        if trade.side is TradeSide.BUY:
            if state.quantity == 0:
                state.open_session, state.open_index, state.trades, state.pnl = session, index.index_of(session), [], ZERO
            state.quantity = C.add(state.quantity, trade.quantity)
            state.cost = C.add(state.cost, C.multiply(trade.quantity, trade.price))
            state.ever_bought = True
            state.trades.append(trade)
            continue
        if state.quantity == 0 and not state.ever_bought:
            exclusions.append(BiasExclusion(trade.trade_id, "sell excluded: position opened before the ledger window"))
            continue
        if trade.quantity > state.quantity:
            raise BiasInputError(
                f"oversell: {trade.trade_id!r} sells {trade.quantity} of {listing_name(trade.instrument)} "
                f"but only {state.quantity} is held"
            )
        average = C.divide(state.cost, state.quantity)
        basis = C.multiply(average, trade.quantity)
        pnl = C.subtract(C.multiply(trade.quantity, trade.price), basis)
        holding = index.index_of(session) - state.open_index
        sells.append(SellEvent(trade, session, pnl, state.open_session, state.open_index, holding))
        sold_today[trade.instrument] = C.add(sold_today.get(trade.instrument, ZERO), pnl)
        state.pnl = C.add(state.pnl, pnl)
        state.trades.append(trade)
        state.quantity = C.subtract(state.quantity, trade.quantity)
        if state.quantity == 0:
            trips.append(RoundTrip(trade.instrument, state.open_session, session, holding, state.pnl, tuple(state.trades)))
            state.cost = ZERO
        else:
            state.cost = C.subtract(state.cost, basis)
    close_day()
    return FoldResult(tuple(sells), tuple(trips), tuple(days), tuple(exclusions))
