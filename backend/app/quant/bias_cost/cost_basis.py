"""Weighted-average position fold per POSITION (spec sections 3, 4): sells with gross P&L, round trips, sell-day snapshots.

Cost basis is price-only (fees excluded) so gross P&L never depends on charge knownness; fees are attributed separately
and once, in overtrading. The method (weighted average) matches `services/holdings.py`. Derived values use `CALC_CONTEXT`.

A round trip is flat -> open -> flat on one POSITION: the ISIN when the trades carry one (NSE and BSE listings of one ISIN are
fungible), else the legacy (symbol, exchange). Each event keeps the listing of the buy that opened the position, whose series
prices it. A sell on a listing with no earlier buy in the supplied trades is
excluded as opened before the window; a sell above the held quantity of a listing that did have buys is an input error.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.enums import TradeSide
from app.domain.holding_key import HoldingKey
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
    open_instrument: Instrument | None = None  # listing of the opening buy; its series carries open_index (None: the trade's own)


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
    __slots__ = ("quantity", "cost", "ever_bought", "open_session", "open_index", "open_instrument", "trades", "pnl")

    def __init__(self) -> None:
        self.quantity = ZERO
        self.cost = ZERO
        self.ever_bought = False
        self.open_session: date | None = None
        self.open_index = 0
        self.open_instrument: Instrument | None = None
        self.trades: list[LedgerTrade] = []
        self.pnl = ZERO


def position_key(trade: LedgerTrade) -> HoldingKey:
    return HoldingKey.of(trade.isin, trade.instrument.symbol, trade.instrument.exchange)


def fold_positions(inputs: ValidatedBiasInputs) -> FoldResult:
    sessions = dict(inputs.sessions)
    indexes = dict(inputs.indexes)
    states: dict[HoldingKey, _State] = {}
    sells: list[SellEvent] = []
    trips: list[RoundTrip] = []
    days: list[SellDay] = []
    exclusions: list[BiasExclusion] = []
    day: date | None = None
    sold_today: dict[HoldingKey, tuple[Instrument, Decimal]] = {}

    def close_day() -> None:
        if day is None or not sold_today:
            return
        paper = tuple(
            PaperPosition(s.open_instrument, s.quantity, C.divide(s.cost, s.quantity))
            for k, s in sorted(states.items(), key=lambda kv: kv[0].sort_key)
            if s.quantity > 0 and k not in sold_today
        )
        realised = tuple(sold_today[k] for k in sorted(sold_today, key=lambda k: k.sort_key))
        days.append(SellDay(day, realised, paper))

    for trade in inputs.trades:
        session = sessions[trade.trade_id]
        if day is not None and session < day:
            raise BiasInputError("session dates must not go backwards across listings")
        if session != day:
            close_day()
            day, sold_today = session, {}
        key = position_key(trade)
        state = states.setdefault(key, _State())
        if trade.side is TradeSide.BUY:
            if state.quantity == 0:
                state.open_instrument = trade.instrument
                state.open_session, state.open_index, state.trades, state.pnl = (
                    session, indexes[trade.instrument].index_of(session), [], ZERO)
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
                f"oversell: {trade.trade_id!r} sells {trade.quantity} of {listing_name(state.open_instrument or trade.instrument)} "
                f"but only {state.quantity} is held"
            )
        index = indexes[state.open_instrument]  # the opening buy's series: open_index and this sell share one calendar
        average = C.divide(state.cost, state.quantity)
        basis = C.multiply(average, trade.quantity)
        pnl = C.subtract(C.multiply(trade.quantity, trade.price), basis)
        holding = index.index_of(session) - state.open_index
        sells.append(SellEvent(trade, session, pnl, state.open_session, state.open_index, holding, state.open_instrument))
        sold_today[key] = (state.open_instrument, C.add(sold_today[key][1] if key in sold_today else ZERO, pnl))
        state.pnl = C.add(state.pnl, pnl)
        state.trades.append(trade)
        state.quantity = C.subtract(state.quantity, trade.quantity)
        if state.quantity == 0:
            trips.append(RoundTrip(state.open_instrument, state.open_session, session, holding, state.pnl, tuple(state.trades)))
            state.cost = ZERO
        else:
            state.cost = C.subtract(state.cost, basis)
    close_day()
    return FoldResult(tuple(sells), tuple(trips), tuple(days), tuple(exclusions))
