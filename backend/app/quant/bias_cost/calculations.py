"""The three `bias-v1` formulas (spec section 4). Costs are signed: positive = the behaviour cost money. Never clamped.

Each function returns `(BiasMetric, facts)`; the facts feed the archetype rules. Unavailable is explicit, never a zero.
Closes are read only through `SeriesIndex.close(..., through=...)`, so no bar after the allowed point can be used.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import TradeSide
from app.quant.market_data.fingerprint import canonical_decimal

from .context import CALC_CONTEXT as C
from .cost_basis import FoldResult
from .errors import Unavailable
from .types import FORMULA_VERSION, BiasKind, BiasMetric, FeeStatus, ListingProvenance
from .validation import ValidatedBiasInputs, listing_name

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class DispositionFacts:
    pgr_minus_plr: Decimal | None


@dataclass(frozen=True)
class ChasingFacts:
    eligible_buys: int
    chase_buys: int


@dataclass(frozen=True)
class OvertradingFacts:
    closed_round_trips: int
    short_term_round_trips: int


def listing_provenance(inputs: ValidatedBiasInputs) -> tuple[ListingProvenance, ...]:
    return tuple(ListingProvenance(i, idx.series.fingerprint) for i, idx in inputs.indexes)


def _text(value: Decimal) -> str:
    return canonical_decimal(value)


def _details(pairs: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(pairs.items()))


def _unavailable(bias: BiasKind, reason: str, inputs: ValidatedBiasInputs, details=()) -> BiasMetric:
    return BiasMetric(bias, FORMULA_VERSION, None, Unavailable(reason), details=tuple(details),
                      listings=listing_provenance(inputs))


def calculate_disposition(inputs: ValidatedBiasInputs, fold: FoldResult) -> tuple[BiasMetric, DispositionFacts]:
    realised_gain = realised_loss = paper_gain = paper_loss = zero_pnl = 0
    for sell_day in fold.sell_days:
        for _, pnl in sell_day.realised:
            if pnl > 0:
                realised_gain += 1
            elif pnl < 0:
                realised_loss += 1
            else:
                zero_pnl += 1
        for position in sell_day.paper:
            index = inputs.index_for(position.instrument)
            i = index.index_of(sell_day.session)
            if i is None:
                reason = f"no {listing_name(position.instrument)} bar on sell day {sell_day.session}: paper P&L unknown"
                return _unavailable(BiasKind.DISPOSITION, reason, inputs), DispositionFacts(None)
            close = index.close(i, through=i)
            if close > position.average_cost:
                paper_gain += 1
            elif close < position.average_cost:
                paper_loss += 1
            else:
                zero_pnl += 1
    gains, losses = realised_gain + paper_gain, realised_loss + paper_loss
    pgr = C.divide(Decimal(realised_gain), Decimal(gains)) if gains else None
    plr = C.divide(Decimal(realised_loss), Decimal(losses)) if losses else None
    diff = C.subtract(pgr, plr) if pgr is not None and plr is not None else None
    details = {
        "realised_gain_positions": str(realised_gain), "realised_loss_positions": str(realised_loss),
        "paper_gain_positions": str(paper_gain), "paper_loss_positions": str(paper_loss),
        "zero_pnl_positions_excluded": str(zero_pnl),
        "pgr": _text(pgr) if pgr is not None else "unavailable",
        "plr": _text(plr) if plr is not None else "unavailable",
        "pgr_minus_plr": _text(diff) if diff is not None else "unavailable",
    }
    facts = DispositionFacts(diff)
    # H's observation unit is the fully CLOSED winning round trip, each counted once (owner, final); PGR/PLR above use
    # the (listing, sell day) unit and partial sells never enter H.
    winners = sorted(t.holding_sessions for t in fold.round_trips if t.gross_pnl > 0)
    if not winners:
        return _unavailable(BiasKind.DISPOSITION, "no winning closed round trip: holding period H is undefined", inputs,
                            _details(details)), facts
    h = winners[(len(winners) - 1) // 2]  # lower median: an integer number of sessions
    details["h_sessions"] = str(h)
    cost, late_losers = ZERO, 0
    for sell in fold.sells:
        if sell.gross_pnl < 0 and sell.holding_sessions > h:
            index = inputs.index_for(sell.trade.instrument)
            sell_index = sell.open_index + sell.holding_sessions
            price_at_h = index.close(sell.open_index + h, through=sell_index)
            cost = C.add(cost, C.multiply(C.subtract(price_at_h, sell.trade.price), sell.trade.quantity))
            late_losers += 1
    details["losing_sells_held_beyond_h"] = str(late_losers)
    metric = BiasMetric(BiasKind.DISPOSITION, FORMULA_VERSION, cost, None, gross_cost_inr=None,
                        details=_details(details), listings=listing_provenance(inputs))
    return metric, facts


def calculate_chasing(inputs: ValidatedBiasInputs) -> tuple[BiasMetric, ChasingFacts]:
    p = inputs.parameters
    n, f = p.chasing_lookback_sessions, p.forward_sessions
    multiplier = C.add(ONE, p.chase_threshold)
    eligible = chases = short_history = 0
    chase_rows: list[tuple[Decimal, Decimal | None]] = []  # (notional, forward return)
    baseline_returns: list[Decimal] = []
    for trade in inputs.trades:
        if trade.side is not TradeSide.BUY:
            continue
        index = inputs.index_for(trade.instrument)
        i = index.index_of(index.session_of(trade.trade_timestamp))
        if i < n + 1:
            short_history += 1
            continue
        eligible += 1
        prior = index.close(i - 1, through=i - 1)  # the buy session and everything after it are never read here
        base = index.close(i - 1 - n, through=i - 1)
        is_chase = prior >= C.multiply(base, multiplier)
        forward = None
        if i + f < index.session_count:  # the forward OUTCOME window; it never decides whether the buy is a chase
            forward = C.subtract(C.divide(index.close(i + f, through=i + f), index.close(i, through=i)), ONE)
        if is_chase:
            chases += 1
            chase_rows.append((C.multiply(trade.quantity, trade.price), forward))
        elif forward is not None:
            baseline_returns.append(forward)
    facts = ChasingFacts(eligible, chases)
    with_forward = [(notional, fwd) for notional, fwd in chase_rows if fwd is not None]
    details = {
        "eligible_buys": str(eligible), "chase_buys": str(chases), "buys_without_prior_history": str(short_history),
        "chase_buys_with_forward": str(len(with_forward)), "non_chase_buys_with_forward": str(len(baseline_returns)),
    }
    if not baseline_returns:
        return _unavailable(BiasKind.CHASING, "no non-chase buy has forward history: baseline undefined", inputs,
                            _details(details)), facts
    total = ZERO
    for value in baseline_returns:
        total = C.add(total, value)  # never `sum()`: its default 28-digit context would round silently
    baseline = C.divide(total, Decimal(len(baseline_returns)))
    details["baseline_forward_return"] = _text(baseline)
    if chases and not with_forward:
        return _unavailable(BiasKind.CHASING, "no chase buy has forward history", inputs, _details(details)), facts
    cost = ZERO
    for notional, fwd in with_forward:
        cost = C.add(cost, C.multiply(notional, C.subtract(baseline, fwd)))
    metric = BiasMetric(BiasKind.CHASING, FORMULA_VERSION, cost, None, details=_details(details),
                        listings=listing_provenance(inputs))
    return metric, facts


def calculate_overtrading(inputs: ValidatedBiasInputs, fold: FoldResult) -> tuple[BiasMetric, OvertradingFacts]:
    limit = inputs.parameters.short_term_sessions
    trips = fold.round_trips
    short = [t for t in trips if t.holding_sessions <= limit]
    facts = OvertradingFacts(len(trips), len(short))
    if not trips:
        return _unavailable(BiasKind.OVERTRADING, "no closed round trips", inputs), facts
    gross = ZERO
    for trip in short:
        gross = C.add(gross, max(ZERO, C.minus(trip.gross_pnl)))
    trades = [t for trip in short for t in trip.trades]
    known = [t for t in trades if t.charges.known]
    unknown_count = len(trades) - len(known)
    known_total = ZERO
    for t in known:
        known_total = C.add(known_total, C.add(t.charges.fees, t.charges.taxes))
    if unknown_count == 0:
        status = FeeStatus.COMPLETE
    else:
        status = FeeStatus.PARTIAL if known else FeeStatus.UNKNOWN
    fees_known = None if status is FeeStatus.UNKNOWN else known_total
    details = {"closed_round_trips": str(len(trips)), "short_term_round_trips": str(len(short)),
               "short_term_trades": str(len(trades))}
    metric = BiasMetric(
        BiasKind.OVERTRADING, FORMULA_VERSION, C.add(gross, fees_known or ZERO), None,
        is_lower_bound=unknown_count > 0, gross_cost_inr=gross, fees_known=fees_known, fee_status=status,
        unknown_fee_trade_count=unknown_count, details=_details(details), listings=listing_provenance(inputs))
    return metric, facts
