"""The backtest loop and the `Strategy` protocol (Feature 005, step 5).

Per common session D, in this order: settle orders queued on the previous session at D's open, mark at D's close, decide
with a view holding bars through D only, queue the orders for the next session. Orders queued on the last session are
recorded `UNFILLED_END_OF_DATA` and never filled. The engine owns the loop only: it reads no clock, fetches nothing and
uses no randomness. `adjusted_close` is never read.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol

from app.domain.enums import TradeSide
from app.domain.instrument import Instrument
from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT
from app.quant.market_data.series import MarketSeries
from .calendar import build_calendar, ordered_series, view_at
from .config import BacktestConfig, BacktestInputError, StrategyIdentity, Unavailable
from .execution import UNFILLED_END_OF_DATA, ExecutionModel, Fill, NextOpenExecution, Order, Rejection, apply_fill
from .portfolio import Portfolio
from .result import BacktestResult, EquityPoint, SeriesRecord


@dataclass(frozen=True)
class StrategyView:
    """Read-only information for one decision: series narrowed to `as_of`, cash and positions. Mappings are copied into
    `MappingProxyType`, so a strategy cannot mutate the engine's state or reach later bars through it."""

    as_of: date
    series: Mapping[Instrument, MarketSeries]
    cash: Decimal
    positions: Mapping[Instrument, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "series", MappingProxyType(dict(self.series)))
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))


class Strategy(Protocol):
    identity: StrategyIdentity

    def decide(self, view: StrategyView) -> Mapping[Instrument, Decimal] | Unavailable:
        """Target whole-share quantities (>= 0) by instrument, or `Unavailable(reason)`. An instrument left out of the
        mapping is held unchanged; selling out needs an explicit zero."""
        ...


def _targets(decision: object, known: Mapping[Instrument, MarketSeries]) -> dict[Instrument, Decimal]:
    if not isinstance(decision, Mapping):
        raise BacktestInputError("a strategy must return a mapping of targets or Unavailable")
    targets: dict[Instrument, Decimal] = {}  # a copy: a retained reference cannot change engine state
    for instrument, raw in decision.items():
        if instrument not in known:
            raise BacktestInputError("a target names an instrument that is not in the backtest")
        if isinstance(raw, bool) or not isinstance(raw, (Decimal, int)):
            raise BacktestInputError("a target must be a Decimal or int number of shares")
        value = Decimal(raw)
        if not value.is_finite() or value.is_signed() and value != 0:
            raise BacktestInputError("a target must be finite and not negative")
        if not value < MAX_AMOUNT or not MIN_INPUT_EXPONENT <= value.as_tuple().exponent <= MAX_INPUT_EXPONENT:
            raise BacktestInputError("a target is out of range")
        if value != value.to_integral_value():
            raise BacktestInputError("a target must be a whole number of shares")
        targets[instrument] = Decimal(int(value))
    return targets


def _orders(targets: Mapping[Instrument, Decimal], portfolio: Portfolio, decided_on: date, next_id: int) -> tuple[Order, ...]:
    """Sells first, then buys; each ordered by (exchange, symbol); ids follow that order."""
    diffs = [(i, t - portfolio.quantity(i)) for i, t in targets.items()]
    key = lambda pair: (pair[0].exchange.value, pair[0].symbol)  # noqa: E731
    sells = sorted((p for p in diffs if p[1] < 0), key=key)
    buys = sorted((p for p in diffs if p[1] > 0), key=key)
    orders = []
    for side, group in ((TradeSide.SELL, sells), (TradeSide.BUY, buys)):
        for instrument, diff in group:
            orders.append(Order(next_id + len(orders), decided_on, instrument, side, abs(diff)))
    return tuple(orders)


def run_backtest(
    series: Sequence[MarketSeries],
    config: BacktestConfig,
    strategy: Strategy,
    execution: ExecutionModel | None = None,
) -> BacktestResult | Unavailable:
    """Simulate `strategy` over the common sessions. Input defects raise `BacktestInputError`; an empty calendar is
    `Unavailable`. Identical inputs and a deterministic strategy give an identical result and fingerprint."""
    if not isinstance(config, BacktestConfig):
        raise BacktestInputError("config must be a BacktestConfig")
    if not isinstance(getattr(strategy, "identity", None), StrategyIdentity) or not callable(getattr(strategy, "decide", None)):
        raise BacktestInputError("strategy must expose an StrategyIdentity `identity` and a `decide` method")
    execution = NextOpenExecution() if execution is None else execution
    inputs = ordered_series(series, config)
    calendar = build_calendar(inputs, config)
    if isinstance(calendar, Unavailable):
        return calendar
    bars = {s.instrument: {b.session_date: b for b in s.bars} for s in inputs}  # full bars; read only on the session itself
    known = {s.instrument: s for s in inputs}

    portfolio = Portfolio.initial(config.initial_cash)
    pending: tuple[Order, ...] = ()
    orders: list[Order] = []
    fills: list[Fill] = []
    rejections: list[Rejection] = []
    unavailable: list[tuple[date, str]] = []
    curve: list[EquityPoint] = []
    last = calendar.dates[-1]

    for session in calendar.dates:
        for order in pending:  # (a) settle at this session's open
            outcome = execution.fill(order, bars[order.instrument][session], portfolio)
            if isinstance(outcome, Fill):
                portfolio = apply_fill(portfolio, outcome)
                fills.append(outcome)
            else:
                rejections.append(outcome)
        held_prices = {i: bars[i][session].close for i, _ in portfolio.positions}  # (b) mark at this session's close
        value = portfolio.mark(held_prices)
        curve.append(EquityPoint(session, value.cash, value.positions_value, value.equity))
        view = StrategyView(session, view_at(inputs, session), portfolio.cash, portfolio.as_mapping())  # (c) decide
        decision = strategy.decide(view)
        pending = ()
        if isinstance(decision, Unavailable):
            unavailable.append((session, decision.reason))
            continue
        pending = _orders(_targets(decision, known), portfolio, session, len(orders) + 1)  # (d) queue for next session
        orders.extend(pending)
        if session == last:
            rejections.extend(Rejection(o.order_id, session, UNFILLED_END_OF_DATA) for o in pending)

    return BacktestResult(
        config=config,
        strategy=strategy.identity,
        series=tuple(SeriesRecord.of(s) for s in inputs),
        calendar_dates=calendar.dates,
        dropped_dates=calendar.dropped_dates,
        equity_curve=tuple(curve),
        orders=tuple(orders),
        fills=tuple(fills),
        rejections=tuple(rejections),
        decisions_unavailable=tuple(unavailable),
        final_cash=portfolio.cash,
        final_positions=portfolio.positions,
    )
