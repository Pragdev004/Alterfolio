"""DataProvenance: facts about one fetch. Facts only; it never states that a requested range was covered."""

from dataclasses import dataclass
from datetime import date, datetime

from .fingerprint import FINGERPRINT_VERSION

NUMERIC_POLICY = "PROVIDER_REPORTED_VERBATIM"  # the provider numbers, unrounded; not a recovered "true" price
CLOSE_SEMANTICS = "provider-defined"
KNOWLEDGE_BASIS = "AS_FETCHED_AT_RETRIEVAL"  # values (notably adjusted_close) are as restated at fetch, not as known at a cutoff

_COUNTS = (
    "rows_returned",
    "empty_rows_excluded",
    "ineligible_bars_excluded",
    "eligible_bars_at_fetch",
)


@dataclass(frozen=True)
class DataProvenance:
    source: str
    request_start: date
    request_end: date
    retrieved_at: datetime
    rows_returned: int
    empty_rows_excluded: int
    ineligible_bars_excluded: int
    eligible_bars_at_fetch: int
    first_eligible_session_date_at_fetch: date | None
    last_eligible_session_date_at_fetch: date | None
    numeric_policy: str = NUMERIC_POLICY
    close_semantics: str = CLOSE_SEMANTICS
    knowledge_basis: str = KNOWLEDGE_BASIS
    fingerprint_version: int = FINGERPRINT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")
        for name in ("request_start", "request_end"):
            value = getattr(self, name)
            if isinstance(value, datetime) or not isinstance(value, date):
                raise TypeError(f"{name} must be a date")
        if self.request_start > self.request_end:
            raise ValueError("request_start must not be after request_end")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        for name in _COUNTS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        first, last = self.first_eligible_session_date_at_fetch, self.last_eligible_session_date_at_fetch
        if self.eligible_bars_at_fetch == 0:
            if first is not None or last is not None:
                raise ValueError("first/last eligible dates must be None when there are no eligible bars")
        else:
            if first is None or last is None:
                raise ValueError("first/last eligible dates are required when there are eligible bars")
            if first > last:
                raise ValueError("first eligible date must not be after the last")
