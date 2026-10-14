"""Immutable Feature 008 contracts: parameters, per-trip labels, per-regime blocks and the result (spec sections 3, 5-7)."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from app.domain.instrument import Instrument
from app.quant.bias_cost.types import BiasAnalysisResult
from app.quant.luck_test.types import LuckResult
from app.quant.market_data.fingerprint import canonical_decimal, iso_utc

from .errors import RegimeInputError, Unavailable

FORMULA_VERSION = "regime-v1"
SCHEMA_VERSION = 1
LIMITATIONS = (
    "Heuristic grouping, not a model of markets: regimes are relative to each listing's own volatility history.",
    "Calibration windows overlap, so the pool is autocorrelated and its effective sample is smaller than its size.",
    "Per-regime Feature 006 results are computed over that regime's round trips only; pooled parts differ from the full run.",
    "Regimes with fewer classified trips than the minimum are Unavailable; no multiple-testing adjustment is applied.",
)


class Regime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


def _int(name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
        raise RegimeInputError(f"{name} must be an int between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class RegimeParameters:
    formula_version: str = FORMULA_VERSION
    volatility_window: int = 60
    low_percentile: int = 33
    high_percentile: int = 67
    min_calibration: int = 120
    min_trips_per_regime: int = 10

    def __post_init__(self) -> None:
        if self.formula_version != FORMULA_VERSION:
            raise RegimeInputError(f"formula_version {self.formula_version!r} is not approved; only {FORMULA_VERSION!r}")
        _int("volatility_window", self.volatility_window, 2, 500)
        _int("low_percentile", self.low_percentile, 1, 99)
        _int("high_percentile", self.high_percentile, 1, 99)
        if self.low_percentile >= self.high_percentile:
            raise RegimeInputError("low_percentile must be below high_percentile")
        _int("min_calibration", self.min_calibration, 1, 10_000)
        _int("min_trips_per_regime", self.min_trips_per_regime, 1, 10_000_000)

    def to_dict(self) -> dict:
        return {"formula_version": self.formula_version, "volatility_window": self.volatility_window,
                "low_percentile": self.low_percentile, "high_percentile": self.high_percentile,
                "min_calibration": self.min_calibration, "min_trips_per_regime": self.min_trips_per_regime}


@dataclass(frozen=True)
class TripRegime:
    """One round trip's label, or why it has none. Exactly one of `regime` and `unavailable` is set."""

    trip_id: str
    instrument: Instrument
    open_session: date
    close_session: date
    regime: Regime | None
    volatility: float | None  # statistic of the last close before the opening date, when computable
    low_threshold: float | None
    high_threshold: float | None
    calibration_count: int | None
    unavailable: Unavailable | None

    def __post_init__(self) -> None:
        if (self.regime is None) == (self.unavailable is None):
            raise RegimeInputError("exactly one of regime and unavailable must be set")

    def to_dict(self) -> dict:
        return {
            "trip_id": self.trip_id, "symbol": self.instrument.symbol, "exchange": self.instrument.exchange.value,
            "open_session": self.open_session.isoformat(), "close_session": self.close_session.isoformat(),
            "regime": None if self.regime is None else self.regime.value, "volatility": self.volatility,
            "low_threshold": self.low_threshold, "high_threshold": self.high_threshold,
            "calibration_count": self.calibration_count,
            "unavailable": None if self.unavailable is None else self.unavailable.to_dict(),
        }


def _bias_dict(result: BiasAnalysisResult) -> dict:
    profile = result.profile
    return {
        "input_fingerprint": result.input_fingerprint,
        "metrics": [
            {"bias": r.metric.bias.value, "input_fingerprint": r.input_fingerprint,
             "cost_inr": None if r.metric.cost_inr is None else canonical_decimal(r.metric.cost_inr),
             "is_lower_bound": r.metric.is_lower_bound,
             "unavailable": None if r.metric.unavailable is None else r.metric.unavailable.reason}
            for r in result.results
        ],
        "profile": ({"unavailable": profile.reason} if not hasattr(profile, "archetype_id")
                    else {"archetype_id": profile.archetype_id, "rule_set_version": profile.rule_set_version}),
        "exclusions": [{"subject": e.subject, "reason": e.reason} for e in result.exclusions],
    }


@dataclass(frozen=True)
class RegimeBlock:
    """One regime: its trips and, at or above the minimum, the unchanged Feature 007 and 006 analyses of those trips."""

    regime: Regime
    trip_ids: tuple[str, ...]  # sorted by (open_session, close_session, trip_id)
    luck: LuckResult | Unavailable
    bias: BiasAnalysisResult | Unavailable

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value, "trip_count": len(self.trip_ids), "trip_ids": list(self.trip_ids),
            "luck": self.luck.to_dict() if isinstance(self.luck, LuckResult) else {"unavailable": self.luck.to_dict()},
            "bias": _bias_dict(self.bias) if isinstance(self.bias, BiasAnalysisResult)
            else {"unavailable": self.bias.to_dict()},
        }


@dataclass(frozen=True)
class RegimeResult:
    parameters: RegimeParameters
    as_of: datetime
    round_trip_count: int
    trips: tuple[TripRegime, ...]  # sorted by (open_session, close_session, trip_id)
    blocks: tuple[RegimeBlock, ...]  # LOW, NORMAL, HIGH, always all three
    exclusions: tuple[tuple[str, str], ...]  # Feature 006 exclusions passed through, (subject, reason)
    unavailable: Unavailable | None  # set when no round trip could be built at all
    input_fingerprint: str
    formula_version: str = FORMULA_VERSION
    schema_version: int = SCHEMA_VERSION
    limitations: tuple[str, ...] = LIMITATIONS

    def __post_init__(self) -> None:
        if len(self.trips) != self.round_trip_count:
            raise RegimeInputError("every round trip must have exactly one TripRegime")
        if tuple(b.regime for b in self.blocks) != (Regime.LOW, Regime.NORMAL, Regime.HIGH):
            raise RegimeInputError("blocks must be LOW, NORMAL, HIGH in that order")
        in_regimes = sum(len(b.trip_ids) for b in self.blocks)
        if in_regimes != sum(1 for t in self.trips if t.regime is not None):
            raise RegimeInputError("regime counts must equal the number of classified trips")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "as_of": iso_utc(self.as_of),
            "unavailable": None if self.unavailable is None else self.unavailable.to_dict(),
            "provenance": {"formula_version": self.formula_version, "input_fingerprint": self.input_fingerprint,
                           "limitations": list(self.limitations)},
            "inputs": {"parameters": self.parameters.to_dict(), "round_trip_count": self.round_trip_count},
            "values": {
                "trips": [t.to_dict() for t in self.trips],
                "regimes": [b.to_dict() for b in self.blocks],
                "unclassified_count": sum(1 for t in self.trips if t.regime is None),
                "exclusions": [{"subject": s, "reason": r} for s, r in self.exclusions],
            },
        }
