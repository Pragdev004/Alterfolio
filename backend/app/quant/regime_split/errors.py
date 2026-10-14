"""Feature 008 errors and `Unavailable`. A defect in the inputs raises; a valid request with no result is `Unavailable`."""

from dataclasses import dataclass
from enum import Enum

MAX_DETAIL_LENGTH = 512


class RegimeInputError(ValueError):
    """An input defect, or a Feature 006/007 contract that no longer holds: the analysis cannot run as specified."""


class UnavailableReason(str, Enum):
    NO_TRIP_SERIES = "NO_TRIP_SERIES"
    MISSING_BAR = "MISSING_BAR"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"  # fewer than window + 1 closes before the opening date
    INSUFFICIENT_CALIBRATION = "INSUFFICIENT_CALIBRATION"  # fewer than `min_calibration` prior observations
    DEGENERATE_THRESHOLDS = "DEGENERATE_THRESHOLDS"  # the two percentile thresholds are equal
    AMBIGUOUS_ISIN = "AMBIGUOUS_ISIN"
    INSUFFICIENT_TRIPS_IN_REGIME = "INSUFFICIENT_TRIPS_IN_REGIME"


@dataclass(frozen=True)
class Unavailable:
    """A valid request that cannot produce a value. It states why; it is never a zero or a default label."""

    reason: UnavailableReason
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reason, UnavailableReason):
            raise RegimeInputError("reason must be an UnavailableReason")
        if not isinstance(self.detail, str) or "\x00" in self.detail or len(self.detail) > MAX_DETAIL_LENGTH:
            raise RegimeInputError(f"detail must be text of at most {MAX_DETAIL_LENGTH} characters without NUL")

    def to_dict(self) -> dict:
        return {"reason": self.reason.value, "detail": self.detail}
