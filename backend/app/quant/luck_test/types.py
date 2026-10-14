"""Immutable Feature 007 contracts. Validated at construction, never repaired. Money and returns are `Decimal`; the only
floats are statistics (distance, excess, percentile, means, interval), produced through `numeric_boundary.to_float`."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from app.domain.instrument import Instrument
from app.domain.limits import ISIN_LENGTH, MAX_BROKER_TRADE_ID_LENGTH
from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT
from app.quant.market_data.fingerprint import canonical_decimal, iso_utc

from .errors import GATE_REASONS, ExclusionReason, LuckInputError, Unavailable, require_text
from .numeric_boundary import interval_indexes
from .rng import RNG_VERSION

SCHEMA_VERSION = 1
FORMULA_VERSION = "luck-v1"  # owner-approved heuristic (spec section 3); the only version this package computes
MAX_TRIPS = 2_000
MAX_UNIVERSE = 5_000
MAX_MEMBERSHIPS = 20_000
MAX_SEED = (1 << 64) - 1
# Provenance stated in every result (spec sections 3, 7, 9): what the numbers are, and what they are not.
ACTUAL_RETURN_BASIS = "LEDGER_PRICES_FEES_EXCLUDED"
ALTERNATIVE_RETURN_BASIS = "SPLIT_ADJUSTED_CLOSE_TO_CLOSE_DIVIDENDS_EXCLUDED"
COVERAGE_DECLARED = "DECLARED"  # the caller declared the set of listings whose corporate actions it reviewed
COVERAGE_UNDECLARED = "UNDECLARED"  # no declaration: the analysis is Unavailable, nothing is assumed clean
LIMITATIONS = (
    "OVERLAPPING_TRIPS_MAKE_INTERVAL_OPTIMISTIC",
    "NOT_PROOF_OF_SKILL_OR_CAUSATION",
    "NIFTY_MEMBERSHIP_AND_UNIVERSE_ARE_CALLER_SUPPLIED",
    "CORPORATE_ACTIONS_ARE_NOT_DETECTED",
    "COVERAGE_IS_A_CALLER_DECLARATION_NOT_PROOF_OF_COMPLETENESS",
)


class Baseline(str, Enum):
    ALT = "ALT"  # random-weight portfolios of pre-trade-similar alternatives
    NIFTY = "NIFTY"  # random 10-stock Nifty 50 portfolios


class IntervalPosition(str, Enum):
    ABOVE_ZERO = "ABOVE_ZERO"
    CONTAINS_ZERO = "CONTAINS_ZERO"
    BELOW_ZERO = "BELOW_ZERO"


def _decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise LuckInputError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise LuckInputError(f"{name} must be finite")
    if not (0 < value < MAX_AMOUNT):
        raise LuckInputError(f"{name} must be above 0 and below {MAX_AMOUNT}")
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise LuckInputError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")
    return value


def _aware_utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise LuckInputError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise LuckInputError(f"{name} must be timezone-aware UTC")
    return value


def _date(name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise LuckInputError(f"{name} must be a date")
    return value


def _count(name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LuckInputError(f"{name} must be an int")
    if not (minimum <= value <= maximum):
        raise LuckInputError(f"{name} must be between {minimum} and {maximum}")
    return value


def _identifier(name: str, value: object) -> str:
    require_text(name, value, MAX_BROKER_TRADE_ID_LENGTH)
    if any(c.isspace() for c in value):
        raise LuckInputError(f"{name} must not contain whitespace")
    return value


def _isin(value: object) -> str:
    """Exactly 12 ASCII [A-Z0-9] characters, never normalised (same rule as the ledger and Feature 006)."""
    if (not isinstance(value, str) or len(value) != ISIN_LENGTH or not value.isascii()
            or not all(c.isdigit() or "A" <= c <= "Z" for c in value)):
        raise LuckInputError(f"isin must be exactly {ISIN_LENGTH} characters of A-Z and 0-9")
    return value


@dataclass(frozen=True)
class TripInput:
    """One FULLY closed round trip (flat -> open -> flat on one listing), summarised from ledger prices; fees excluded."""

    trip_id: str
    instrument: Instrument
    isin: str | None
    open_session: date  # decision date `d`, in the listing's exchange-local calendar
    close_session: date  # exit date `j`
    cost_inr: Decimal  # sum(buy quantity * price)
    proceeds_inr: Decimal  # sum(sell quantity * price)

    def __post_init__(self) -> None:
        _identifier("trip_id", self.trip_id)
        if not isinstance(self.instrument, Instrument):
            raise LuckInputError("instrument must be an Instrument")
        if self.isin is not None:
            _isin(self.isin)
        _date("open_session", self.open_session)
        _date("close_session", self.close_session)
        if self.close_session < self.open_session:
            raise LuckInputError("close_session must not be before open_session")
        _decimal("cost_inr", self.cost_inr)
        _decimal("proceeds_inr", self.proceeds_inr)


@dataclass(frozen=True)
class Candidate:
    """One listing in the alternative universe. The universe holds exactly one listing per ISIN."""

    instrument: Instrument
    isin: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise LuckInputError("instrument must be an Instrument")
        _isin(self.isin)


@dataclass(frozen=True)
class Membership:
    """`isin` was a Nifty 50 member on every date in [from_date, to_date); `to_date` None = still a member."""

    isin: str
    from_date: date
    to_date: date | None = None

    def __post_init__(self) -> None:
        _isin(self.isin)
        _date("from_date", self.from_date)
        if self.to_date is not None:
            _date("to_date", self.to_date)
            if self.to_date <= self.from_date:
                raise LuckInputError("to_date must be after from_date")

    def active_on(self, d: date) -> bool:
        return self.from_date <= d and (self.to_date is None or d < self.to_date)


@dataclass(frozen=True)
class LuckParameters:
    """Versioned run parameters (spec section 3). `seed` and `as_of` are explicit inputs; nothing reads a clock."""

    seed: int
    as_of: datetime
    formula_version: str = FORMULA_VERSION
    portfolio_count: int = 500
    max_alternatives: int = 10
    min_alternatives: int = 5
    nifty_portfolio_size: int = 10
    bootstrap_replicates: int = 10_000
    confidence_level: Decimal = Decimal("0.95")
    min_trips: int = 10
    momentum_lookback: int = 20
    volatility_lookback: int = 60

    def __post_init__(self) -> None:
        _count("seed", self.seed, 0, MAX_SEED)
        _aware_utc("as_of", self.as_of)
        if self.formula_version != FORMULA_VERSION:
            raise LuckInputError(f"formula_version {self.formula_version!r} is not approved; only {FORMULA_VERSION!r}")
        _count("portfolio_count", self.portfolio_count, 1, 100_000)
        _count("max_alternatives", self.max_alternatives, 1, 50)
        _count("min_alternatives", self.min_alternatives, 1, self.max_alternatives)
        _count("nifty_portfolio_size", self.nifty_portfolio_size, 1, 50)
        _count("bootstrap_replicates", self.bootstrap_replicates, 1, 1_000_000)
        _count("min_trips", self.min_trips, 1, MAX_TRIPS)
        _count("momentum_lookback", self.momentum_lookback, 1, 1_000)
        _count("volatility_lookback", self.volatility_lookback, 2, 1_000)
        level = self.confidence_level
        if not isinstance(level, Decimal) or not level.is_finite() or not (0 < level < 1):
            raise LuckInputError("confidence_level must be a Decimal strictly between 0 and 1")
        if not (MIN_INPUT_EXPONENT <= level.as_tuple().exponent <= MAX_INPUT_EXPONENT):
            raise LuckInputError("confidence_level exponent is outside the input range")
        try:
            interval_indexes(self.bootstrap_replicates, level)
        except ValueError as exc:
            raise LuckInputError(str(exc)) from exc

    @property
    def history_needed(self) -> int:
        """Bars strictly before the decision date that both similarity features need."""
        return max(self.momentum_lookback, self.volatility_lookback) + 1


@dataclass(frozen=True)
class AlternativePick:
    """A selected alternative in rank order. `return_ratio` is None when it had no bar on the exit session (lost)."""

    rank: int
    instrument: Instrument
    isin: str
    distance: float  # squared Euclidean distance on z-scored pre-trade features (a statistic)
    return_ratio: Decimal | None

    def __post_init__(self) -> None:
        _count("rank", self.rank, 1, 1_000)
        if not isinstance(self.instrument, Instrument):
            raise LuckInputError("instrument must be an Instrument")
        _isin(self.isin)
        if not isinstance(self.distance, float):
            raise LuckInputError("distance must be a float statistic")
        if self.return_ratio is not None and not (isinstance(self.return_ratio, Decimal) and self.return_ratio.is_finite()):
            raise LuckInputError("return_ratio must be a finite Decimal or None")


@dataclass(frozen=True)
class BaselineOutcome:
    """One trip against one baseline: a number set, or `Unavailable`; exactly one of the two."""

    baseline: Baseline
    portfolio_count: int  # portfolios drawn (0 when unavailable)
    pool_size: int  # stocks the portfolios drew from (after lost ones)
    lost_count: int  # candidates dropped for lacking an exit bar
    beaten: int | None  # portfolios the actual return exceeded
    ties: int | None  # portfolios equal to the actual return
    mean_return: Decimal | None  # mean portfolio return (exact Decimal)
    excess: float | None  # actual return - mean portfolio return (a statistic)
    percentile: float | None  # (beaten + ties / 2) / portfolio_count (a statistic)
    unavailable: Unavailable | None

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, Baseline):
            raise LuckInputError("baseline must be a Baseline")
        _count("portfolio_count", self.portfolio_count, 0, 100_000)
        _count("pool_size", self.pool_size, 0, MAX_UNIVERSE)
        _count("lost_count", self.lost_count, 0, MAX_UNIVERSE)
        if self.unavailable is not None:
            if not isinstance(self.unavailable, Unavailable):
                raise LuckInputError("unavailable must be an Unavailable")
            if any(v is not None for v in (self.beaten, self.ties, self.mean_return, self.excess, self.percentile)):
                raise LuckInputError("an unavailable outcome carries no numbers")
            if self.portfolio_count != 0:
                raise LuckInputError("an unavailable outcome drew no portfolios")
        else:
            if self.beaten is None or self.ties is None or self.mean_return is None:
                raise LuckInputError("an available outcome needs its counts and mean return")
            if not isinstance(self.excess, float) or not isinstance(self.percentile, float):
                raise LuckInputError("excess and percentile must be floats")
            if self.beaten + self.ties > self.portfolio_count:
                raise LuckInputError("beaten + ties cannot exceed portfolio_count")


@dataclass(frozen=True)
class CandidateExclusion:
    """One candidate (or Nifty member) left out of one trip's pool, and why. `instrument` is None for a member ISIN that
    is not in the universe."""

    baseline: Baseline
    isin: str
    instrument: Instrument | None
    reason: ExclusionReason

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, Baseline) or not isinstance(self.reason, ExclusionReason):
            raise LuckInputError("baseline and reason must be a Baseline and an ExclusionReason")
        _isin(self.isin)
        if self.instrument is not None and not isinstance(self.instrument, Instrument):
            raise LuckInputError("instrument must be an Instrument or None")


@dataclass(frozen=True)
class TripLuck:
    trip_id: str
    instrument: Instrument
    open_session: date
    close_session: date
    actual_return: Decimal | None  # (proceeds - cost) / cost; always computable for a valid trip
    picks: tuple[AlternativePick, ...]
    alt: BaselineOutcome
    nifty: BaselineOutcome
    evaluated: bool  # False = stopped by a gate before any selection or draw; the screening fields are then meaningless
    exclusions: tuple[CandidateExclusion, ...] = ()  # sorted by (baseline, ISIN)
    zero_variance_features: tuple[str, ...] = ()  # features with no cross-sectional spread (z = 0 for everyone)
    actual_return_basis: str = ACTUAL_RETURN_BASIS  # `actual_return` is ledger-price based and EXCLUDES fees

    def __post_init__(self) -> None:
        _identifier("trip_id", self.trip_id)
        if not isinstance(self.picks, tuple) or not all(isinstance(p, AlternativePick) for p in self.picks):
            raise LuckInputError("picks must be a tuple of AlternativePick")
        if not isinstance(self.exclusions, tuple) or not all(isinstance(e, CandidateExclusion) for e in self.exclusions):
            raise LuckInputError("exclusions must be a tuple of CandidateExclusion")
        if not isinstance(self.zero_variance_features, tuple):
            raise LuckInputError("zero_variance_features must be a tuple")
        if self.alt.baseline is not Baseline.ALT or self.nifty.baseline is not Baseline.NIFTY:
            raise LuckInputError("alt and nifty outcomes must carry their own baseline")
        if not isinstance(self.evaluated, bool):
            raise LuckInputError("evaluated must be a bool")
        if self.actual_return_basis != ACTUAL_RETURN_BASIS:
            raise LuckInputError(f"actual_return_basis must be {ACTUAL_RETURN_BASIS!r}")
        gated = [o.unavailable.reason for o in (self.alt, self.nifty)
                 if o.unavailable is not None and o.unavailable.reason in GATE_REASONS]
        if self.evaluated:
            if gated:
                raise LuckInputError("an evaluated trip cannot carry a gate reason")
        else:
            if len(gated) != 2 or gated[0] is not gated[1]:
                raise LuckInputError("a trip that was not evaluated needs the same gate reason on both baselines")
            if self.picks or self.exclusions or self.zero_variance_features:
                raise LuckInputError("a trip that was not evaluated has no picks, exclusions or features")

    @property
    def lost_alternative_count(self) -> int | None:
        """None when the trip was not evaluated (zero would read as 'nothing was lost')."""
        return self.alt.lost_count if self.evaluated else None

    @property
    def survivorship_flag(self) -> bool | None:
        """None when the trip was not evaluated."""
        return (self.alt.lost_count > 0 or self.nifty.lost_count > 0) if self.evaluated else None


@dataclass(frozen=True)
class BaselineSummary:
    """Aggregate over the trips available for one baseline.

    Point estimates (means) need at least one available trip, else `mean_unavailable`. The bootstrap interval needs
    `min_trips` available trips, else `ci_unavailable`; an unavailable interval does not make the means unavailable."""

    baseline: Baseline
    trips_used: int
    trips_unavailable: int
    unavailable_counts: tuple[tuple[str, int], ...]  # (reason, trips), sorted by reason
    trips_evaluated: int  # trips that got past every gate (their outcome may still be unavailable)
    survivorship_trip_count: int | None  # over evaluated trips only; None when no trip was evaluated
    mean_excess: float | None
    mean_percentile: float | None
    mean_unavailable: Unavailable | None
    ci_lower: float | None
    ci_upper: float | None
    position: IntervalPosition | None
    ci_unavailable: Unavailable | None

    def __post_init__(self) -> None:
        _count("trips_evaluated", self.trips_evaluated, 0, MAX_TRIPS)
        if (self.survivorship_trip_count is None) != (self.trips_evaluated == 0):
            raise LuckInputError("survivorship_trip_count is None exactly when no trip was evaluated")
        if (self.mean_unavailable is None) != (self.mean_excess is not None and self.mean_percentile is not None):
            raise LuckInputError("exactly one of the means and mean_unavailable must be set")
        if (self.ci_unavailable is None) != (self.ci_lower is not None and self.ci_upper is not None):
            raise LuckInputError("exactly one of the interval and ci_unavailable must be set")
        if (self.position is None) != (self.ci_unavailable is not None):
            raise LuckInputError("position is set exactly when the interval is")
        if self.mean_unavailable is not None and self.ci_unavailable is None:
            raise LuckInputError("an interval needs point estimates")


@dataclass(frozen=True)
class LuckResult:
    parameters: LuckParameters
    input_fingerprint: str
    series_fingerprints: tuple[tuple[str, str, str], ...]  # (symbol, exchange, fingerprint) of every listing used, sorted
    trips: tuple[TripLuck, ...]  # sorted by (open_session, close_session, trip_id)
    alt_summary: BaselineSummary
    nifty_summary: BaselineSummary
    corporate_action_coverage: str  # DECLARED or UNDECLARED
    known_corporate_action_listing_count: int  # len(corporate_action_listings): entries in the supplied known-actions
    # set, whether or not any is traded, in the universe or excluded; NOT an exclusion count
    unavailable: Unavailable | None  # set exactly when coverage is UNDECLARED: no trip is evaluated
    formula_version: str = FORMULA_VERSION
    rng_version: str = RNG_VERSION
    schema_version: int = SCHEMA_VERSION
    actual_return_basis: str = ACTUAL_RETURN_BASIS
    alternative_return_basis: str = ALTERNATIVE_RETURN_BASIS
    limitations: tuple[str, ...] = LIMITATIONS

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, LuckParameters):
            raise LuckInputError("parameters must be LuckParameters")
        if self.corporate_action_coverage not in (COVERAGE_DECLARED, COVERAGE_UNDECLARED):
            raise LuckInputError("corporate_action_coverage must be DECLARED or UNDECLARED")
        if (self.corporate_action_coverage == COVERAGE_UNDECLARED) != (self.unavailable is not None):
            raise LuckInputError("unavailable is set exactly when corporate-action coverage is UNDECLARED")
        if self.unavailable is not None and (
                not isinstance(self.unavailable, Unavailable)
                or self.unavailable.reason.value != "CORPORATE_ACTION_COVERAGE_UNDECLARED"):
            raise LuckInputError("unavailable must be CORPORATE_ACTION_COVERAGE_UNDECLARED")
        _count("known_corporate_action_listing_count", self.known_corporate_action_listing_count, 0, 10_000_000)
        if any(t.actual_return_basis != self.actual_return_basis for t in self.trips):
            raise LuckInputError("every trip's actual_return_basis must equal the result's")
        require_text("input_fingerprint", self.input_fingerprint, 128)
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise LuckInputError(f"schema_version must be the int {SCHEMA_VERSION}")
        if self.formula_version != self.parameters.formula_version:
            raise LuckInputError("formula_version must equal the parameters' formula_version")
        if self.alt_summary.baseline is not Baseline.ALT or self.nifty_summary.baseline is not Baseline.NIFTY:
            raise LuckInputError("summaries must carry their own baseline")

    def to_dict(self) -> dict:
        p = self.parameters
        return {
            "schema_version": self.schema_version,
            "as_of": iso_utc(p.as_of),
            # Top level on purpose: non-null means the whole analysis is unavailable (no trip was evaluated).
            "unavailable": _unavailable_dict(self.unavailable),
            "provenance": {
                "formula_version": self.formula_version,
                "rng_version": self.rng_version,
                "seed": p.seed,
                "input_fingerprint": self.input_fingerprint,
                "series": [list(row) for row in self.series_fingerprints],
                "actual_return_basis": self.actual_return_basis,
                "alternative_return_basis": self.alternative_return_basis,
                "corporate_action_coverage": self.corporate_action_coverage,
                "known_corporate_action_listing_count": self.known_corporate_action_listing_count,
                "unavailable": _unavailable_dict(self.unavailable),
                "limitations": list(self.limitations),
            },
            "inputs": {
                "portfolio_count": p.portfolio_count, "max_alternatives": p.max_alternatives,
                "min_alternatives": p.min_alternatives, "nifty_portfolio_size": p.nifty_portfolio_size,
                "bootstrap_replicates": p.bootstrap_replicates, "confidence_level": canonical_decimal(p.confidence_level),
                "min_trips": p.min_trips, "momentum_lookback": p.momentum_lookback,
                "volatility_lookback": p.volatility_lookback, "trip_count": len(self.trips),
            },
            "values": {
                "trips": [_trip_dict(t) for t in self.trips],
                "summaries": {s.baseline.value: _summary_dict(s) for s in (self.alt_summary, self.nifty_summary)},
            },
        }


def _unavailable_dict(u: Unavailable | None) -> dict | None:
    return None if u is None else {"reason": u.reason.value, "detail": u.detail}


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else canonical_decimal(value)


def _outcome_dict(o: BaselineOutcome, evaluated: bool) -> dict:
    return {
        "portfolio_count": o.portfolio_count if evaluated else None, "pool_size": o.pool_size if evaluated else None,
        "lost_count": o.lost_count if evaluated else None, "beaten": o.beaten,
        "ties": o.ties, "mean_return": _dec(o.mean_return), "excess": o.excess, "percentile": o.percentile,
        "unavailable": _unavailable_dict(o.unavailable),
    }


def _trip_dict(t: TripLuck) -> dict:
    return {
        "trip_id": t.trip_id,
        "instrument": {"symbol": t.instrument.symbol, "exchange": t.instrument.exchange.value},
        "open_session": t.open_session.isoformat(), "close_session": t.close_session.isoformat(),
        "evaluated": t.evaluated, "actual_return": _dec(t.actual_return), "actual_return_basis": t.actual_return_basis,
        "lost_alternative_count": t.lost_alternative_count, "survivorship_flag": t.survivorship_flag,
        # Screening results exist only for evaluated trips: null (never [] or 0) says "not evaluated".
        "zero_variance_features": list(t.zero_variance_features) if t.evaluated else None,
        "exclusions": None if not t.evaluated else [
            {"baseline": e.baseline.value, "isin": e.isin, "reason": e.reason.value,
             "symbol": None if e.instrument is None else e.instrument.symbol,
             "exchange": None if e.instrument is None else e.instrument.exchange.value}
            for e in t.exclusions
        ],
        "picks": None if not t.evaluated else [
            {"rank": a.rank, "symbol": a.instrument.symbol, "exchange": a.instrument.exchange.value, "isin": a.isin,
             "distance": a.distance, "return_ratio": _dec(a.return_ratio)}
            for a in t.picks
        ],
        "alt": _outcome_dict(t.alt, t.evaluated), "nifty": _outcome_dict(t.nifty, t.evaluated),
    }


def _summary_dict(s: BaselineSummary) -> dict:
    return {
        "trips_used": s.trips_used, "trips_unavailable": s.trips_unavailable,
        "unavailable_counts": [list(row) for row in s.unavailable_counts], "trips_evaluated": s.trips_evaluated,
        "survivorship_trip_count": s.survivorship_trip_count, "mean_excess": s.mean_excess,
        "mean_percentile": s.mean_percentile, "mean_unavailable": _unavailable_dict(s.mean_unavailable),
        "ci_lower": s.ci_lower, "ci_upper": s.ci_upper,
        "position": None if s.position is None else s.position.value, "ci_unavailable": _unavailable_dict(s.ci_unavailable),
    }
