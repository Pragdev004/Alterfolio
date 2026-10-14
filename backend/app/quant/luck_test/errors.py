"""Feature 007 errors and `Unavailable`. Independent of every sibling quant package (spec section 8)."""

from dataclasses import dataclass
from enum import Enum

MAX_DETAIL_LENGTH = 256


class LuckInputError(ValueError):
    """An input defect: the analysis cannot run as specified. A valid request with no result is `Unavailable` instead."""


def require_text(name: str, value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise LuckInputError(f"{name} must be text")
    if not value.strip():
        raise LuckInputError(f"{name} must not be empty")
    if "\x00" in value:
        raise LuckInputError(f"{name} must not contain NUL")
    if len(value) > limit:
        raise LuckInputError(f"{name} must be at most {limit} characters")
    return value


class UnavailableReason(str, Enum):
    NOT_CLOSED_AT_AS_OF = "NOT_CLOSED_AT_AS_OF"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    CORPORATE_ACTION_UNKNOWN = "CORPORATE_ACTION_UNKNOWN"  # declared coverage does not include the listing
    CORPORATE_ACTION_COVERAGE_UNDECLARED = "CORPORATE_ACTION_COVERAGE_UNDECLARED"  # no declaration: nothing is assumed clean
    NO_TRIP_SERIES = "NO_TRIP_SERIES"
    MISSING_BAR = "MISSING_BAR"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_ALTERNATIVES = "INSUFFICIENT_ALTERNATIVES"
    NIFTY_POOL_TOO_SMALL = "NIFTY_POOL_TOO_SMALL"
    NO_MEMBERSHIP = "NO_MEMBERSHIP"
    NO_AVAILABLE_TRIPS = "NO_AVAILABLE_TRIPS"  # no point estimate: no trip has an outcome for the baseline
    INSUFFICIENT_TRIPS = "INSUFFICIENT_TRIPS"  # point estimates exist, the bootstrap interval does not


class ExclusionReason(str, Enum):
    """Why one candidate or Nifty member was left out of one trip's pool (recorded, never silent)."""

    CORPORATE_ACTION = "CORPORATE_ACTION"
    CORPORATE_ACTION_UNKNOWN = "CORPORATE_ACTION_UNKNOWN"
    SAME_AS_TRADED = "SAME_AS_TRADED"
    NO_SERIES = "NO_SERIES"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NO_ENTRY_BAR = "NO_ENTRY_BAR"
    NOT_IN_UNIVERSE = "NOT_IN_UNIVERSE"
    NO_EXIT_BAR = "NO_EXIT_BAR"


@dataclass(frozen=True)
class Unavailable:
    """A valid request that cannot produce a value. It states why; it is never a zero or an estimate."""

    reason: UnavailableReason
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reason, UnavailableReason):
            raise LuckInputError("reason must be an UnavailableReason")
        if not isinstance(self.detail, str) or "\x00" in self.detail or len(self.detail) > MAX_DETAIL_LENGTH:
            raise LuckInputError(f"detail must be text of at most {MAX_DETAIL_LENGTH} characters without NUL")


# Reasons that stop a trip BEFORE any selection or draw (the trip is then NOT evaluated); every other reason is an outcome
# of an evaluation that did run.
GATE_REASONS = frozenset({
    UnavailableReason.CORPORATE_ACTION_COVERAGE_UNDECLARED, UnavailableReason.CORPORATE_ACTION,
    UnavailableReason.CORPORATE_ACTION_UNKNOWN, UnavailableReason.NO_TRIP_SERIES, UnavailableReason.NOT_CLOSED_AT_AS_OF,
    UnavailableReason.MISSING_BAR,
})
