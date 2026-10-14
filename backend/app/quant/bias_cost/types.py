"""Immutable Feature 006 contracts. Validated at construction, never repaired; money and quantity are `Decimal`.

Unknown charges are represented by `ChargeValue.unknown()` (no numbers), never by a stored 0 (spec section 3).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from app.domain.enums import Currency, TradeSide
from app.domain.instrument import Instrument
from app.domain.limits import ISIN_LENGTH, MAX_BROKER_TRADE_ID_LENGTH
from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT

from .context import CALC_CONTEXT
from .errors import BiasInputError, Unavailable, require_text

SCHEMA_VERSION = 1
MAX_IDENTITY_LENGTH = 64
MAX_FINGERPRINT_LENGTH = 128
MAX_ITEMS = 100_000


FORMULA_VERSION = "bias-v1"  # owner-approved heuristic (spec section 3); the only version this package computes


class BiasKind(str, Enum):
    DISPOSITION = "DISPOSITION"
    CHASING = "CHASING"
    OVERTRADING = "OVERTRADING"


class FeeStatus(str, Enum):
    COMPLETE = "COMPLETE"  # every involved trade has known charges
    PARTIAL = "PARTIAL"  # some known, some unknown
    UNKNOWN = "UNKNOWN"  # none known


def _decimal(name: str, value: object, *, positive: bool) -> Decimal:
    if not isinstance(value, Decimal):
        raise BiasInputError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise BiasInputError(f"{name} must be finite")
    if not ((value > 0) if positive else (value >= 0)) or value >= MAX_AMOUNT:
        raise BiasInputError(f"{name} must be {'above' if positive else 'at least'} 0 and below {MAX_AMOUNT}")
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise BiasInputError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")
    return value


def _aware_utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise BiasInputError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise BiasInputError(f"{name} must be timezone-aware UTC")
    return value


def _count(name: str, value: object, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BiasInputError(f"{name} must be an int")
    if value < minimum:
        raise BiasInputError(f"{name} must be at least {minimum}")
    return value


def _schema_version(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise BiasInputError(f"schema_version must be the int {SCHEMA_VERSION}")


def _identifier(name: str, value: object) -> str:
    """Identifiers are used verbatim as keys, so any whitespace (leading, trailing, embedded, newline) is rejected."""
    require_text(name, value, MAX_BROKER_TRADE_ID_LENGTH)
    if any(c.isspace() for c in value):
        raise BiasInputError(f"{name} must not contain whitespace")
    return value


def _isin(value: str) -> None:
    """Exactly 12 ASCII [A-Z0-9] characters, never normalized (same rule as `services/ledger.py::_isin`)."""
    if (not isinstance(value, str) or len(value) != ISIN_LENGTH or not value.isascii()
            or not all(c.isdigit() or "A" <= c <= "Z" for c in value)):
        raise BiasInputError(f"isin must be exactly {ISIN_LENGTH} characters of A-Z and 0-9")


def _ratio(name: str, value: object) -> Decimal:
    """A finite Decimal in [0, 1] within the input exponent range (thresholds and shares)."""
    if not isinstance(value, Decimal) or not value.is_finite() or not (0 <= value <= 1):
        raise BiasInputError(f"{name} must be a Decimal between 0 and 1")
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise BiasInputError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")
    return value


def _pairs(name: str, value: object) -> None:
    """(name, canonical text) pairs, unique and sorted by name."""
    _tuple_of(name, value, tuple)
    previous: str | None = None
    for pair in value:
        if len(pair) != 2:
            raise BiasInputError(f"each {name} item must be a (name, value) pair")
        key, text = pair
        require_text(f"{name} name", key, MAX_IDENTITY_LENGTH)
        require_text(f"{name} {key!r}", text, 256)
        if previous is not None and not previous < key:
            raise BiasInputError(f"{name} must be unique and sorted by name")
        previous = key


def _tuple_of(name: str, value: object, item_type: type) -> None:
    if not isinstance(value, tuple):
        raise BiasInputError(f"{name} must be a tuple")
    if len(value) > MAX_ITEMS:
        raise BiasInputError(f"{name} is too long")
    if not all(isinstance(item, item_type) for item in value):
        raise BiasInputError(f"{name} items must be {item_type.__name__}")


@dataclass(frozen=True)
class ChargeValue:
    """Fees and taxes of one trade. Known: both Decimals >= 0. Unknown: both None (imported rows), never 0."""

    known: bool
    fees: Decimal | None = None
    taxes: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.known, bool):
            raise BiasInputError("known must be a bool")
        if self.known:
            _decimal("fees", self.fees, positive=False)
            _decimal("taxes", self.taxes, positive=False)
        elif self.fees is not None or self.taxes is not None:
            raise BiasInputError("unknown charges must carry no amounts")

    @classmethod
    def unknown(cls) -> "ChargeValue":
        return cls(known=False)


@dataclass(frozen=True)
class LedgerTrade:
    """One effective ledger trade (EXECUTED, not superseded), already mapped from storage by a service.

    `trade_id` is the INTERNAL ledger row identity (`trades.id`, a UUID rendered as text): present on every row and
    unique, which `broker_trade_id` is not (it is NULL on manual rows and may legitimately contain spaces there).
    A service must never put a `broker_trade_id` here. No call site exists yet (Step 2+), so this is the intended
    mapping, not an observed one; the accepted format is unchanged: non-empty, no whitespace, at most 128 characters.
    """

    trade_id: str
    instrument: Instrument
    isin: str | None
    side: TradeSide
    quantity: Decimal
    price: Decimal
    trade_timestamp: datetime
    charges: ChargeValue
    currency: Currency = Currency.INR

    def __post_init__(self) -> None:
        _identifier("trade_id", self.trade_id)
        if not isinstance(self.instrument, Instrument):
            raise BiasInputError("instrument must be an Instrument")
        if self.isin is not None:
            _isin(self.isin)
        if not isinstance(self.side, TradeSide):
            raise BiasInputError("side must be a TradeSide")
        _decimal("quantity", self.quantity, positive=True)
        _decimal("price", self.price, positive=True)
        _aware_utc("trade_timestamp", self.trade_timestamp)
        if not isinstance(self.charges, ChargeValue):
            raise BiasInputError("charges must be a ChargeValue")
        if self.currency is not Currency.INR:
            raise BiasInputError("only INR trades are supported")


@dataclass(frozen=True)
class BiasParameters:
    """Versioned run parameters. Thresholds are added when their values are approved (plan 006 section 7)."""

    chasing_lookback_sessions: int
    window_start: datetime
    window_end: datetime
    formula_version: str
    rule_set_version: str
    forward_sessions: int = 20
    chase_threshold: Decimal = Decimal("0.10")
    short_term_sessions: int = 5
    min_round_trips: int = 10
    churner_share: Decimal = Decimal("0.30")
    chaser_share: Decimal = Decimal("0.40")
    disposition_threshold: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        _count("chasing_lookback_sessions", self.chasing_lookback_sessions, 1)
        _count("forward_sessions", self.forward_sessions, 1)
        _count("short_term_sessions", self.short_term_sessions, 0)
        _count("min_round_trips", self.min_round_trips, 1)
        for name in ("chase_threshold", "churner_share", "chaser_share", "disposition_threshold"):
            _ratio(name, getattr(self, name))
        _aware_utc("window_start", self.window_start)
        _aware_utc("window_end", self.window_end)
        if self.window_start > self.window_end:
            raise BiasInputError("window_start must not be after window_end")
        require_text("formula_version", self.formula_version, MAX_IDENTITY_LENGTH)
        require_text("rule_set_version", self.rule_set_version, MAX_IDENTITY_LENGTH)


@dataclass(frozen=True)
class BiasExclusion:
    """Something left out of a calculation, and why (never silently dropped)."""

    subject: str
    reason: str

    def __post_init__(self) -> None:
        require_text("subject", self.subject, MAX_BROKER_TRADE_ID_LENGTH)
        require_text("reason", self.reason, 1024)


@dataclass(frozen=True)
class ListingProvenance:
    """Which listing's series fed a metric (never a fallback to another exchange)."""

    instrument: Instrument
    series_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise BiasInputError("instrument must be an Instrument")
        require_text("series_fingerprint", self.series_fingerprint, MAX_FINGERPRINT_LENGTH)


@dataclass(frozen=True)
class BiasMetric:
    """One bias outcome: a signed cost in INR (positive = it cost money) or `Unavailable`; exactly one of the two.

    `cost_inr` is the exact internal value (presentation quantizes to 6 places). `gross_cost_inr` is the price-only part;
    fee fields apply only where fees are part of the cost (overtrading). Unknown fees are counted, never summed or zero.
    """

    bias: BiasKind
    formula_version: str
    cost_inr: Decimal | None
    unavailable: Unavailable | None
    is_lower_bound: bool = False
    exclusions: tuple[BiasExclusion, ...] = ()
    gross_cost_inr: Decimal | None = None
    fees_known: Decimal | None = None  # sum of KNOWN fees+taxes; None when none is known or fees do not apply
    fee_status: FeeStatus | None = None
    unknown_fee_trade_count: int = 0
    details: tuple[tuple[str, str], ...] = ()
    listings: tuple[ListingProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.bias, BiasKind):
            raise BiasInputError("bias must be a BiasKind")
        require_text("formula_version", self.formula_version, MAX_IDENTITY_LENGTH)
        if (self.cost_inr is None) == (self.unavailable is None):
            raise BiasInputError("exactly one of cost_inr and unavailable must be set")
        if self.cost_inr is not None:
            if not isinstance(self.cost_inr, Decimal) or not self.cost_inr.is_finite():
                raise BiasInputError("cost_inr must be a finite Decimal")
            # Owner decision 2026-10-14: exact internal Decimal, signed, never clamped, quantized only for presentation.
        elif not isinstance(self.unavailable, Unavailable):
            raise BiasInputError("unavailable must be an Unavailable")
        if not isinstance(self.is_lower_bound, bool):
            raise BiasInputError("is_lower_bound must be a bool")
        if self.is_lower_bound and self.cost_inr is None:
            raise BiasInputError("a lower bound needs a cost")
        _tuple_of("exclusions", self.exclusions, BiasExclusion)
        for name in ("gross_cost_inr", "fees_known"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise BiasInputError(f"{name} must be a finite Decimal")
        if self.gross_cost_inr is not None and self.cost_inr is None:
            raise BiasInputError("gross_cost_inr needs a cost")
        if self.fees_known is not None and self.fees_known < 0:
            raise BiasInputError("fees_known must not be negative")
        _count("unknown_fee_trade_count", self.unknown_fee_trade_count, 0)
        _pairs("details", self.details)
        _tuple_of("listings", self.listings, ListingProvenance)
        if self.fee_status is None:
            if self.fees_known is not None or self.unknown_fee_trade_count:
                raise BiasInputError("fee fields need a fee_status")
        else:
            if not isinstance(self.fee_status, FeeStatus):
                raise BiasInputError("fee_status must be a FeeStatus")
            if (self.fee_status is FeeStatus.UNKNOWN) != (self.fees_known is None):
                raise BiasInputError("fees_known is None exactly when fee_status is UNKNOWN")
            if (self.fee_status is FeeStatus.COMPLETE) != (self.unknown_fee_trade_count == 0):
                raise BiasInputError("unknown_fee_trade_count is 0 exactly when fee_status is COMPLETE")
            if self.cost_inr is not None:
                if self.gross_cost_inr is None:
                    raise BiasInputError("a cost with fee_status needs gross_cost_inr")
                if self.cost_inr != CALC_CONTEXT.add(self.gross_cost_inr, self.fees_known or Decimal(0)):  # exact, not 28-digit
                    raise BiasInputError("cost_inr must equal gross_cost_inr plus known fees")
                if self.fee_status is not FeeStatus.COMPLETE and not self.is_lower_bound:
                    raise BiasInputError("a cost with unknown fees must be a lower bound")


@dataclass(frozen=True)
class BiasResult:
    """A metric with its provenance: schema version, currency, parameters and input fingerprint."""

    metric: BiasMetric
    parameters: BiasParameters
    input_fingerprint: str
    currency: Currency = Currency.INR
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.metric, BiasMetric) or not isinstance(self.parameters, BiasParameters):
            raise BiasInputError("metric and parameters must be BiasMetric and BiasParameters")
        require_text("input_fingerprint", self.input_fingerprint, MAX_FINGERPRINT_LENGTH)
        if self.currency is not Currency.INR:
            raise BiasInputError("only INR results are supported")
        _schema_version(self.schema_version)
        if self.metric.formula_version != self.parameters.formula_version:
            raise BiasInputError("metric formula_version must equal the parameters' formula_version")


@dataclass(frozen=True)
class BehaviourProfile:
    """Rule-based archetype. `supporting_metrics` are (name, canonical text) pairs, unique and sorted by name."""

    archetype_id: str
    rule_set_version: str
    supporting_metrics: tuple[tuple[str, str], ...]
    input_fingerprint: str

    def __post_init__(self) -> None:
        require_text("archetype_id", self.archetype_id, MAX_IDENTITY_LENGTH)
        require_text("rule_set_version", self.rule_set_version, MAX_IDENTITY_LENGTH)
        require_text("input_fingerprint", self.input_fingerprint, MAX_FINGERPRINT_LENGTH)
        _tuple_of("supporting_metrics", self.supporting_metrics, tuple)
        previous: str | None = None
        for pair in self.supporting_metrics:
            if len(pair) != 2:
                raise BiasInputError("each supporting metric must be a (name, value) pair")
            name, value = pair
            require_text("metric name", name, MAX_IDENTITY_LENGTH)
            require_text(f"metric {name!r}", value, 256)
            if previous is not None and not previous < name:
                raise BiasInputError("supporting_metrics must be unique and sorted by name")
            previous = name


@dataclass(frozen=True)
class BiasAnalysisResult:
    """The whole analysis: one result per requested bias, the profile (or why not), and run-level exclusions."""

    results: tuple[BiasResult, ...]
    profile: BehaviourProfile | Unavailable
    exclusions: tuple[BiasExclusion, ...]
    input_fingerprint: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _tuple_of("results", self.results, BiasResult)
        if not isinstance(self.profile, (BehaviourProfile, Unavailable)):
            raise BiasInputError("profile must be a BehaviourProfile or Unavailable")
        _tuple_of("exclusions", self.exclusions, BiasExclusion)
        require_text("input_fingerprint", self.input_fingerprint, MAX_FINGERPRINT_LENGTH)
        _schema_version(self.schema_version)
        kinds = [r.metric.bias for r in self.results]
        if len(set(kinds)) != len(kinds):
            raise BiasInputError("at most one result per bias")
        # One run: one parameter set. Per-bias and profile fingerprints may differ from each other and from the
        # analysis fingerprint (each covers only its relevant inputs; spec section 7, test 11), so none is compared.
        for r in self.results:
            if r.parameters != self.results[0].parameters:
                raise BiasInputError("all results must share the same parameters")
        if isinstance(self.profile, BehaviourProfile):
            if self.results and self.profile.rule_set_version != self.results[0].parameters.rule_set_version:
                raise BiasInputError("profile rule_set_version must equal the parameters' rule_set_version")
