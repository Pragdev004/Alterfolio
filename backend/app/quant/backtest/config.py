"""Backtest configuration, strategy identity, input errors and `Unavailable` (Feature 005, step 1).

Everything here is validated at construction and never repaired: invalid input raises `BacktestInputError`. No clock,
no float, no randomness. Money is `Decimal`; parameters are canonical text so identical inputs fingerprint identically.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain.enums import Currency
from app.domain.numeric import MAX_AMOUNT, MAX_INPUT_EXPONENT, MIN_INPUT_EXPONENT
from app.quant.market_data.fingerprint import canonical_decimal

# The only price basis this version supports: execution at the provider's `open`, valuation at its `close`, both
# split-adjusted; dividends excluded; `adjusted_close` is never read (plan 005, D1).
PRICE_BASIS = "SPLIT_ADJUSTED_OPEN_CLOSE"

MAX_IDENTITY_LENGTH = 64
MAX_PARAMETER_VALUE_LENGTH = 256
MAX_PARAMETERS = 64


class BacktestInputError(ValueError):
    """An input defect: the backtest cannot be run as specified. Never a runtime 'no data' outcome (that is Unavailable)."""


def _text(name: str, value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise BacktestInputError(f"{name} must be text")
    if not value.strip():
        raise BacktestInputError(f"{name} must not be empty")
    if "\x00" in value:
        raise BacktestInputError(f"{name} must not contain NUL")
    if len(value) > limit:
        raise BacktestInputError(f"{name} must be at most {limit} characters")
    return value


@dataclass(frozen=True)
class Unavailable:
    """A valid request that cannot produce a value. It states why; it is never a zero or an estimate."""

    reason: str

    def __post_init__(self) -> None:
        _text("reason", self.reason, MAX_PARAMETER_VALUE_LENGTH * 4)


@dataclass(frozen=True)
class BacktestConfig:
    start_date: date  # inclusive; first session that may be traded
    end_date: date  # inclusive
    initial_cash: Decimal
    currency: Currency
    trial_count: int  # how many strategy variants were tried before this one (>= 1); recorded, not persisted (D7)
    price_basis: str = PRICE_BASIS

    def __post_init__(self) -> None:
        if isinstance(self.trial_count, bool) or not isinstance(self.trial_count, int) or self.trial_count < 1:
            raise BacktestInputError("trial_count must be an int >= 1 (not bool)")
        for name in ("start_date", "end_date"):
            value = getattr(self, name)
            if isinstance(value, datetime) or not isinstance(value, date):
                raise BacktestInputError(f"{name} must be a date")
        if self.start_date > self.end_date:
            raise BacktestInputError("start_date must not be after end_date")
        cash = self.initial_cash
        if not isinstance(cash, Decimal):
            raise BacktestInputError("initial_cash must be a Decimal")
        if not cash.is_finite():
            raise BacktestInputError("initial_cash must be finite")
        if not (0 < cash < MAX_AMOUNT):
            raise BacktestInputError(f"initial_cash must be above 0 and below {MAX_AMOUNT}")
        _check_exponent("initial_cash", cash)
        if not isinstance(self.currency, Currency):
            raise BacktestInputError("currency must be a Currency")
        if self.price_basis != PRICE_BASIS:
            raise BacktestInputError(f"price_basis must be {PRICE_BASIS!r}")


def _check_exponent(name: str, value: Decimal) -> None:
    exponent = value.as_tuple().exponent
    if not (MIN_INPUT_EXPONENT <= exponent <= MAX_INPUT_EXPONENT):
        raise BacktestInputError(f"{name} exponent {exponent} is outside [{MIN_INPUT_EXPONENT}, {MAX_INPUT_EXPONENT}]")


def _canonical_value(name: str, value: object) -> str:
    if isinstance(value, bool):
        raise BacktestInputError(f"parameter {name!r} must be text, an int or a Decimal, not bool")
    if isinstance(value, str):
        return _text(f"parameter {name!r}", value, MAX_PARAMETER_VALUE_LENGTH)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BacktestInputError(f"parameter {name!r} must be finite")
        _check_exponent(f"parameter {name!r}", value)
        return canonical_decimal(value)
    raise BacktestInputError(f"parameter {name!r} must be text, an int or a Decimal (floats are not allowed)")


@dataclass(frozen=True)
class StrategyIdentity:
    """Who made the decisions. Recorded verbatim in the result and fingerprint.

    The strategy owner MUST change `version` whenever behavior changes; the engine only records it, it cannot verify it.
    `parameters` are canonical text pairs, unique and sorted by key (use `create` to build them from a mapping).
    """

    strategy_id: str
    version: str
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _text("strategy_id", self.strategy_id, MAX_IDENTITY_LENGTH)
        _text("version", self.version, MAX_IDENTITY_LENGTH)
        if not isinstance(self.parameters, tuple):
            raise BacktestInputError("parameters must be a tuple of (key, value) text pairs")
        if len(self.parameters) > MAX_PARAMETERS:
            raise BacktestInputError(f"at most {MAX_PARAMETERS} parameters")
        previous: str | None = None
        for pair in self.parameters:
            if not (isinstance(pair, tuple) and len(pair) == 2):
                raise BacktestInputError("each parameter must be a (key, value) tuple")
            key, value = pair
            _text("parameter key", key, MAX_IDENTITY_LENGTH)
            _text(f"parameter {key!r}", value, MAX_PARAMETER_VALUE_LENGTH)
            if previous is not None and not previous < key:
                raise BacktestInputError("parameters must be unique and sorted by key")
            previous = key

    @classmethod
    def create(cls, strategy_id: str, version: str, parameters: Mapping[str, object]) -> "StrategyIdentity":
        """Canonicalize: sort by key, ints and Decimals to exact text, reject floats and bools."""
        if not isinstance(parameters, Mapping):
            raise BacktestInputError("parameters must be a mapping")
        pairs = []
        for key, value in parameters.items():
            _text("parameter key", key, MAX_IDENTITY_LENGTH)
            pairs.append((key, _canonical_value(key, value)))
        return cls(strategy_id, version, tuple(sorted(pairs)))
