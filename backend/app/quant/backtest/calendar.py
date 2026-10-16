"""Backtest input validation, the common-session calendar and point-in-time views (Feature 005, step 3).

All time logic keys on `session_date`, never on provider timestamps. The calendar is the INNER JOIN of session dates across
every series within the requested range; dates missing from any series are dropped, counted and never filled. A view for
decision date D is built with Feature 004's `truncated_to` at the exchange-local midnight that ends D (derived from the
date and the fixed offset, never from a clock), so no bar after D is reachable.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType

from app.domain.instrument import Instrument
from app.quant.market_data.series import MarketSeries
from .config import BacktestConfig, BacktestInputError, Unavailable

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Calendar:
    """`dates`: sorted common session dates inside the period. `dropped_dates`: dates inside the period present in at
    least one series but not in all of them (sorted, each counted once)."""

    dates: tuple[date, ...]
    dropped_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.dates:
            raise BacktestInputError("a calendar holds at least one date; an empty one is Unavailable")


def ordered_series(series: Sequence[MarketSeries], config: BacktestConfig) -> tuple[MarketSeries, ...]:
    """Validate the inputs and return them sorted by (exchange, symbol). Defects raise `BacktestInputError`."""
    if isinstance(series, (str, bytes, Mapping)) or not isinstance(series, Sequence) or not series:
        raise BacktestInputError("series must be a non-empty sequence of MarketSeries")
    if not all(isinstance(s, MarketSeries) for s in series):
        raise BacktestInputError("every series must be a MarketSeries")
    ordered = tuple(sorted(series, key=lambda s: (s.instrument.exchange.value, s.instrument.symbol)))
    if len({s.instrument for s in ordered}) != len(ordered):
        raise BacktestInputError("instruments must be distinct")
    if any(s.currency != config.currency for s in ordered):
        raise BacktestInputError("every series currency must equal the configured currency")
    if len({s.exchange_utc_offset for s in ordered}) != 1:
        raise BacktestInputError("every series must have the same exchange UTC offset")
    for s in ordered:
        if not s.bars:
            raise BacktestInputError(f"series {s.instrument.symbol} has no bars")
        if s.observed_through < config.end_date:
            raise BacktestInputError(
                f"series {s.instrument.symbol} is observed through {s.observed_through}, before end_date "
                f"{config.end_date}; the period is never clipped"
            )
    return ordered


def build_calendar(series: Sequence[MarketSeries], config: BacktestConfig) -> Calendar | Unavailable:
    """The common session dates in [start_date, end_date], or `Unavailable` when there are none."""
    ordered = ordered_series(series, config)
    per_series = [
        {b.session_date for b in s.bars if config.start_date <= b.session_date <= config.end_date} for s in ordered
    ]
    common = set.intersection(*per_series)
    dropped = set.union(*per_series) - common
    if not common:
        return Unavailable("no session date inside the period is present in every series")
    return Calendar(dates=tuple(sorted(common)), dropped_dates=tuple(sorted(dropped)))


def decision_instant(session: date, offset: timedelta) -> datetime:
    """The UTC instant of local midnight at the END of `session` (the start of the next local day). No clock."""
    local_midnight = datetime.combine(session + _ONE_DAY, time.min)
    return (local_midnight - offset).replace(tzinfo=timezone.utc)


def view_at(series: Sequence[MarketSeries], session: date) -> Mapping[Instrument, MarketSeries]:
    """Each series narrowed to bars with `session_date <= session`, as a read-only mapping in (exchange, symbol) order."""
    views: dict[Instrument, MarketSeries] = {}
    for s in series:
        try:
            views[s.instrument] = s.truncated_to(decision_instant(session, s.exchange_utc_offset))
        except ValueError as exc:
            raise BacktestInputError(f"cannot build the view for {session} of {s.instrument.symbol}: {exc}") from exc
    return MappingProxyType(views)
