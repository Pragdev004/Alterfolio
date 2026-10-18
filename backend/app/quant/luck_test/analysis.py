"""`analyze_luck`: the Feature 007 entry point (spec sections 2-9). Pure and deterministic: no clock, no I/O, seeded draws only.

Per trip, selection reads only closes before the decision date (`PreTradeView`); exit prices are read AFTER the alternatives
are chosen, and an alternative without an exit bar is dropped and counted, never replaced or estimated. Every candidate or
Nifty member left out of a trip's pool is recorded with a reason.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import Currency
from app.domain.instrument import Instrument
from app.quant.market_data.exchange_time import local_date
from app.quant.market_data.series import MarketSeries

from .bootstrap import bootstrap_mean_interval, excess_and_percentile, mean, position
from .errors import MAX_DETAIL_LENGTH, ExclusionReason, LuckInputError, Unavailable, UnavailableReason
from .features import ListingBars, feature_vector, pool_stats, rank_candidates
from .fingerprint import input_fingerprint
from .numeric_boundary import CALC, ONE
from .portfolios import alt_portfolio_returns, compare, nifty_portfolio_returns
from .rng import SplitMix64, derive_seed
from .types import (
    COVERAGE_DECLARED, COVERAGE_UNDECLARED, MAX_MEMBERSHIPS, MAX_TRIPS, MAX_UNIVERSE, AlternativePick, Baseline,
    BaselineOutcome, BaselineSummary, Candidate, CandidateExclusion, LuckParameters, LuckResult, Membership, TripInput,
    TripLuck,
)

R = UnavailableReason
X = ExclusionReason


@dataclass(frozen=True)
class _Context:
    parameters: LuckParameters
    bars: dict[Instrument, ListingBars]
    universe: tuple[Candidate, ...]  # sorted by ISIN
    by_isin: dict[str, Candidate]
    membership: tuple[Membership, ...]
    corporate_actions: frozenset[Instrument]
    reviewed: frozenset[Instrument] | None  # None = undeclared: the trip gate fails every trip before this is read


def _validate(trips, series, universe, nifty50, corporate_action_listings, corporate_action_reviewed, parameters):
    if not isinstance(parameters, LuckParameters):
        raise LuckInputError("parameters must be LuckParameters")
    trips, universe, nifty50 = tuple(trips), tuple(universe), tuple(nifty50)
    if len(trips) > MAX_TRIPS or len(universe) > MAX_UNIVERSE or len(nifty50) > MAX_MEMBERSHIPS:
        raise LuckInputError("too many trips, universe candidates or membership intervals")
    if not all(isinstance(t, TripInput) for t in trips):
        raise LuckInputError("trips must be TripInput")
    if not all(isinstance(c, Candidate) for c in universe):
        raise LuckInputError("universe must hold Candidate")
    if not all(isinstance(m, Membership) for m in nifty50):
        raise LuckInputError("nifty50 must hold Membership")
    if not isinstance(series, Mapping):
        raise LuckInputError("series must be a mapping of listing to MarketSeries")
    for key, value in series.items():
        if not isinstance(key, Instrument) or not isinstance(value, MarketSeries) or value.instrument != key:
            raise LuckInputError("each series must be keyed by its own listing (symbol, exchange)")
        if value.currency is not Currency.INR:
            raise LuckInputError("only INR series are supported")
    if not isinstance(corporate_action_listings, frozenset) or not all(
        isinstance(i, Instrument) for i in corporate_action_listings
    ):
        raise LuckInputError("corporate_action_listings must be a frozenset of Instrument")
    if corporate_action_reviewed is not None and (
        not isinstance(corporate_action_reviewed, frozenset)
        or not all(isinstance(i, Instrument) for i in corporate_action_reviewed)
    ):
        raise LuckInputError("corporate_action_reviewed must be a frozenset of Instrument or None")
    ids = [t.trip_id for t in trips]
    if len(set(ids)) != len(ids):
        raise LuckInputError("duplicate trip_id")
    isins = [c.isin for c in universe]
    if len(set(isins)) != len(isins):
        raise LuckInputError("the universe must hold one listing per ISIN (duplicate ISIN)")
    listings = [c.instrument for c in universe]
    if len(set(listings)) != len(listings):
        raise LuckInputError("duplicate instrument in the universe")
    return trips, universe, nifty50


def _unavailable(baseline: Baseline, reason: R, detail: str = "", lost: int = 0) -> BaselineOutcome:
    return BaselineOutcome(baseline, 0, 0, lost, None, None, None, None, None, Unavailable(reason, detail))


def _available(
    baseline: Baseline, actual: Decimal, returns: tuple[Decimal, ...], pool_size: int, lost: int
) -> BaselineOutcome:
    beaten, ties, mean_return = compare(actual, returns)
    excess, percentile = excess_and_percentile(actual, mean_return, beaten, ties, len(returns))
    return BaselineOutcome(baseline, len(returns), pool_size, lost, beaten, ties, mean_return, excess, percentile, None,
                           portfolio_returns=returns)


def _ca_reason(instrument: Instrument, ctx: _Context) -> X | None:
    """A known corporate action, or (declared coverage only) a listing the caller did not review. Never inferred."""
    if instrument in ctx.corporate_actions:
        return X.CORPORATE_ACTION
    if instrument not in ctx.reviewed:
        return X.CORPORATE_ACTION_UNKNOWN
    return None


UNDECLARED = Unavailable(
    R.CORPORATE_ACTION_COVERAGE_UNDECLARED, "no corporate-action coverage was declared, so no listing is assumed clean")


def _trip_gate(trip: TripInput, ctx: _Context) -> Unavailable | None:
    """Checks that apply to both baselines. Undeclared coverage comes first: nothing else is evaluated without it."""
    if ctx.reviewed is None:
        return UNDECLARED
    ca = _ca_reason(trip.instrument, ctx)
    if ca is not None:
        return Unavailable(R[ca.name], "traded listing: known corporate action or outside the declared review coverage")
    own = ctx.bars.get(trip.instrument)
    if own is None:
        return Unavailable(R.NO_TRIP_SERIES, "no series for the traded listing")
    if trip.close_session >= local_date(ctx.parameters.as_of, own.offset):
        return Unavailable(R.NOT_CLOSED_AT_AS_OF, "close_session is not before the as_of exchange date")
    if own.close_on(trip.open_session) is None or own.close_on(trip.close_session) is None:
        return Unavailable(R.MISSING_BAR, "the traded listing has no bar on its open or close session")
    return None


def _return_ratio(entry: Decimal, exit_: Decimal) -> Decimal:
    return CALC.subtract(CALC.divide(exit_, entry), ONE)


def _pool_reason(trip: TripInput, cand: Candidate, ctx: _Context) -> X | None:
    """Reasons a universe listing cannot be a comparison stock for this trip (shared by both baselines)."""
    if cand.instrument == trip.instrument or (trip.isin is not None and cand.isin == trip.isin):
        return X.SAME_AS_TRADED
    ca = _ca_reason(cand.instrument, ctx)
    if ca is not None:
        return ca
    return None if cand.instrument in ctx.bars else X.NO_SERIES


def _alt_baseline(
    trip: TripInput, actual: Decimal, ctx: _Context, notes: list[CandidateExclusion]
) -> tuple[tuple[AlternativePick, ...], BaselineOutcome, tuple[str, ...]]:
    p, d, j = ctx.parameters, trip.open_session, trip.close_session
    own_vector = feature_vector(ctx.bars[trip.instrument].before(d, p.history_needed),
                                p.momentum_lookback, p.volatility_lookback)
    if own_vector is None:
        return (), _unavailable(Baseline.ALT, R.INSUFFICIENT_HISTORY,
                                f"the traded listing needs {p.history_needed} bars before the decision date"), ()
    scored: list[tuple[Candidate, tuple[float, float]]] = []
    for cand in ctx.universe:
        why = _pool_reason(trip, cand, ctx)
        vector = None
        if why is None:
            bars = ctx.bars[cand.instrument]
            vector = feature_vector(bars.before(d, p.history_needed), p.momentum_lookback, p.volatility_lookback)
            if vector is None:
                why = X.INSUFFICIENT_HISTORY
            elif bars.close_on(d) is None:
                why = X.NO_ENTRY_BAR
        if why is not None:
            notes.append(CandidateExclusion(Baseline.ALT, cand.isin, cand.instrument, why))
        else:
            scored.append((cand, vector))
    if not scored:
        return (), _unavailable(Baseline.ALT, R.INSUFFICIENT_ALTERNATIVES, "no eligible alternative before selection"), ()
    stats = pool_stats([v for _, v in scored])  # the candidate pool only; the traded stock is standardised with it
    ranked = rank_candidates(stats.standardise(own_vector), [(c, stats.standardise(v)) for c, v in scored])
    ranked = ranked[:p.max_alternatives]
    # Selection is finished. Exit prices are read only now; a missing exit bar drops the alternative (never refilled).
    picks: list[AlternativePick] = []
    returns: list[Decimal] = []
    for rank, (cand, distance) in enumerate(ranked, start=1):
        bars = ctx.bars[cand.instrument]
        exit_ = bars.close_on(j)
        ratio = None if exit_ is None else _return_ratio(bars.close_on(d), exit_)
        picks.append(AlternativePick(rank, cand.instrument, cand.isin, distance, ratio))
        if ratio is not None:
            returns.append(ratio)
    lost = len(picks) - len(returns)
    if len(returns) < p.min_alternatives:
        return tuple(picks), _unavailable(
            Baseline.ALT, R.INSUFFICIENT_ALTERNATIVES,
            f"{len(returns)} alternatives with an exit bar, {p.min_alternatives} needed", lost), stats.zero_variance
    rng = SplitMix64(derive_seed(p.seed, p.formula_version, trip.trip_id, "alt"))
    portfolios = alt_portfolio_returns(rng, returns, p.portfolio_count)
    return tuple(picks), _available(Baseline.ALT, actual, portfolios, len(returns), lost), stats.zero_variance


def _nifty_baseline(
    trip: TripInput, actual: Decimal, ctx: _Context, notes: list[CandidateExclusion]
) -> BaselineOutcome:
    p, d, j = ctx.parameters, trip.open_session, trip.close_session
    active = sorted({m.isin for m in ctx.membership if m.active_on(d)})
    if not active:
        return _unavailable(Baseline.NIFTY, R.NO_MEMBERSHIP, "no Nifty 50 membership interval covers the decision date")
    returns: list[Decimal] = []
    lost = 0
    for isin in active:
        cand = ctx.by_isin.get(isin)
        if cand is None:
            notes.append(CandidateExclusion(Baseline.NIFTY, isin, None, X.NOT_IN_UNIVERSE))
            continue
        why = _pool_reason(trip, cand, ctx)
        entry = exit_ = None
        if why is None:
            bars = ctx.bars[cand.instrument]
            entry, exit_ = bars.close_on(d), bars.close_on(j)
            if entry is None:
                why = X.NO_ENTRY_BAR
            elif exit_ is None:
                why = X.NO_EXIT_BAR
                lost += 1
        if why is not None:
            notes.append(CandidateExclusion(Baseline.NIFTY, isin, cand.instrument, why))
        else:
            returns.append(_return_ratio(entry, exit_))
    if len(returns) < p.nifty_portfolio_size:
        return _unavailable(Baseline.NIFTY, R.NIFTY_POOL_TOO_SMALL,
                            f"{len(returns)} eligible members with prices, {p.nifty_portfolio_size} needed", lost)
    rng = SplitMix64(derive_seed(p.seed, p.formula_version, trip.trip_id, "nifty"))
    portfolios = nifty_portfolio_returns(rng, returns, p.nifty_portfolio_size, p.portfolio_count)
    return _available(Baseline.NIFTY, actual, portfolios, len(returns), lost)


def _evaluate(trip: TripInput, ctx: _Context) -> TripLuck:
    actual = CALC.subtract(CALC.divide(trip.proceeds_inr, trip.cost_inr), ONE)
    gate = _trip_gate(trip, ctx)
    notes: list[CandidateExclusion] = []
    zero_variance: tuple[str, ...] = ()
    if gate is not None:
        alt = _unavailable(Baseline.ALT, gate.reason, gate.detail)
        nifty = _unavailable(Baseline.NIFTY, gate.reason, gate.detail)
        picks: tuple[AlternativePick, ...] = ()
    else:
        picks, alt, zero_variance = _alt_baseline(trip, actual, ctx, notes)
        nifty = _nifty_baseline(trip, actual, ctx, notes)
    notes.sort(key=lambda e: (e.baseline.value, e.isin))
    return TripLuck(trip.trip_id, trip.instrument, trip.open_session, trip.close_session, actual, picks, alt, nifty,
                    evaluated=gate is None, exclusions=tuple(notes), zero_variance_features=zero_variance)


def _summarise(baseline: Baseline, trips: tuple[TripLuck, ...], p: LuckParameters) -> BaselineSummary:
    pairs = [(t, t.alt if baseline is Baseline.ALT else t.nifty) for t in trips]
    outcomes = [o for _, o in pairs]
    used = [o for o in outcomes if o.unavailable is None]
    counts = tuple(sorted(Counter(o.unavailable.reason.value for o in outcomes if o.unavailable is not None).items()))
    evaluated = [o for t, o in pairs if t.evaluated]
    survivorship = sum(1 for o in evaluated if o.lost_count > 0) if evaluated else None
    common = (baseline, len(used), len(outcomes) - len(used), counts, len(evaluated), survivorship)
    if not used:
        reasons = {o.unavailable.reason for o in outcomes}
        if len(reasons) == 1:  # every trip stopped for the SAME reason: that reason is the cause, not the sample size
            cause = outcomes[0].unavailable
            why = Unavailable(cause.reason, f"all {len(outcomes)} trips: {cause.detail}"[:MAX_DETAIL_LENGTH])
            return BaselineSummary(*common, None, None, why, None, None, None, why)
        gone = Unavailable(R.NO_AVAILABLE_TRIPS, "no trip has an outcome for this baseline")
        return BaselineSummary(*common, None, None, gone, None, None, None,
                               Unavailable(R.INSUFFICIENT_TRIPS, f"0 trips available, {p.min_trips} needed"))
    excess = [o.excess for o in used]
    mean_excess, mean_percentile = mean(excess), mean([o.percentile for o in used])
    if len(used) < p.min_trips:
        return BaselineSummary(*common, mean_excess, mean_percentile, None, None, None, None,
                               Unavailable(R.INSUFFICIENT_TRIPS, f"{len(used)} trips available, {p.min_trips} needed"))
    stream = "boot_alt" if baseline is Baseline.ALT else "boot_nifty"
    rng = SplitMix64(derive_seed(p.seed, p.formula_version, "", stream))
    lower, upper = bootstrap_mean_interval(excess, rng, p.bootstrap_replicates, p.confidence_level)
    return BaselineSummary(*common, mean_excess, mean_percentile, None, lower, upper, position(lower, upper), None)


def analyze_luck(
    trips: Iterable[TripInput],
    series: Mapping[Instrument, MarketSeries],
    universe: Iterable[Candidate],
    nifty50: Iterable[Membership],
    corporate_action_listings: frozenset[Instrument],
    parameters: LuckParameters,
    *,
    corporate_action_reviewed: frozenset[Instrument] | None = None,
) -> LuckResult:
    """Corporate-action coverage is a prerequisite. `corporate_action_reviewed` is the caller's declaration of the listings whose
    corporate actions it reviewed (its completeness is the caller's responsibility, not proven here); `None` = undeclared and
    the result is Unavailable (`CORPORATE_ACTION_COVERAGE_UNDECLARED`). With a declaration, `corporate_action_listings` (known
    actions, effect unresolved) are excluded as `CORPORATE_ACTION` and any listing outside it as `CORPORATE_ACTION_UNKNOWN`."""
    trips, universe, nifty50 = _validate(
        trips, series, universe, nifty50, corporate_action_listings, corporate_action_reviewed, parameters)
    used_listings = {t.instrument for t in trips} | {c.instrument for c in universe}
    bars = {i: ListingBars.build(s) for i, s in series.items() if i in used_listings}
    ctx = _Context(
        parameters, bars, tuple(sorted(universe, key=lambda c: c.isin)), {c.isin: c for c in universe}, nifty50,
        corporate_action_listings, corporate_action_reviewed)
    ordered = sorted(trips, key=lambda t: (t.open_session, t.close_session, t.trip_id))
    evaluated = tuple(_evaluate(t, ctx) for t in ordered)
    fingerprints = tuple(sorted((i.symbol, i.exchange.value, b.fingerprint) for i, b in bars.items()))
    return LuckResult(
        parameters=parameters,
        input_fingerprint=input_fingerprint(
            trips, fingerprints, universe, nifty50, corporate_action_listings, parameters, corporate_action_reviewed),
        series_fingerprints=fingerprints,
        trips=evaluated,
        alt_summary=_summarise(Baseline.ALT, evaluated, parameters),
        nifty_summary=_summarise(Baseline.NIFTY, evaluated, parameters),
        corporate_action_coverage=COVERAGE_UNDECLARED if corporate_action_reviewed is None else COVERAGE_DECLARED,
        known_corporate_action_listing_count=len(corporate_action_listings),
        unavailable=UNDECLARED if corporate_action_reviewed is None else None,
    )
