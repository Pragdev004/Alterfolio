"""Feature 006 round trips -> Feature 007 `TripInput`, one to one (spec section 4).

Identity is the opening buy's ledger id: ledger ids are unique (`validate_inputs` rejects duplicates) and a trade belongs to at
most one round trip, so same-listing same-day re-entries (different opening buys) never collide. Nothing is matched on dates.
Structural violations mean Feature 006 no longer behaves as pinned by the contract test, so they raise.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import TradeSide
from app.quant.bias_cost.context import CALC_CONTEXT as C
from app.quant.bias_cost.cost_basis import RoundTrip
from app.quant.luck_test.errors import LuckInputError
from app.quant.luck_test.types import TripInput

from .errors import RegimeInputError, Unavailable, UnavailableReason


@dataclass(frozen=True)
class MappedTrip:
    round_trip: RoundTrip
    trip: TripInput
    unavailable: Unavailable | None  # AMBIGUOUS_ISIN: listed, in no regime


def _isin(round_trip: RoundTrip) -> tuple[str | None, Unavailable | None]:
    values = [t.isin for t in round_trip.trades]
    distinct = set(values)
    if distinct == {None}:
        return None, None
    if len(distinct) == 1:
        return values[0], None
    return None, Unavailable(UnavailableReason.AMBIGUOUS_ISIN, "the trades of this round trip carry mixed or conflicting ISINs")


def map_round_trips(round_trips: Iterable[RoundTrip]) -> tuple[MappedTrip, ...]:
    mapped: list[MappedTrip] = []
    trip_ids: set[str] = set()
    trade_ids: set[str] = set()
    for rt in round_trips:
        trades = rt.trades
        if not trades or trades[0].side is not TradeSide.BUY or trades[-1].side is not TradeSide.SELL:
            raise RegimeInputError("a round trip must open with a BUY and close with a SELL")
        if any(t.instrument != rt.instrument for t in trades):
            raise RegimeInputError("a round trip must stay on one listing")
        zero = Decimal(0)
        bought, sold, cost, proceeds = zero, zero, zero, zero
        for t in trades:
            value = C.multiply(t.quantity, t.price)
            if t.side is TradeSide.BUY:
                bought, cost = C.add(bought, t.quantity), C.add(cost, value)
            else:
                sold, proceeds = C.add(sold, t.quantity), C.add(proceeds, value)
        if bought != sold:
            raise RegimeInputError("a round trip must sell exactly what it bought")
        trip_id = trades[0].trade_id
        if trip_id in trip_ids:
            raise RegimeInputError(f"duplicate trip identity {trip_id!r}")
        trip_ids.add(trip_id)
        for t in trades:
            if t.trade_id in trade_ids:
                raise RegimeInputError(f"trade {t.trade_id!r} belongs to more than one round trip")
            trade_ids.add(t.trade_id)
        isin, ambiguous = _isin(rt)
        try:
            trip = TripInput(trip_id, rt.instrument, isin, rt.open_session, rt.close_session, cost, proceeds)
        except LuckInputError as exc:
            raise RegimeInputError(f"round trip {trip_id!r} is not a valid Feature 007 trip: {exc}") from exc
        mapped.append(MappedTrip(rt, trip, ambiguous))
    return tuple(mapped)
