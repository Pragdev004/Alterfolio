"""Feature 006 errors and `Unavailable`. Independent of `quant/backtest` (plan 006, decision D6 option (a))."""

from dataclasses import dataclass

MAX_REASON_LENGTH = 1024


class BiasInputError(ValueError):
    """An input defect: the analysis cannot run as specified. A valid request with no result is `Unavailable` instead."""


def require_text(name: str, value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise BiasInputError(f"{name} must be text")
    if not value.strip():
        raise BiasInputError(f"{name} must not be empty")
    if "\x00" in value:
        raise BiasInputError(f"{name} must not contain NUL")
    if len(value) > limit:
        raise BiasInputError(f"{name} must be at most {limit} characters")
    return value


@dataclass(frozen=True)
class Unavailable:
    """A valid request that cannot produce a value. It states why; it is never a zero or an estimate."""

    reason: str

    def __post_init__(self) -> None:
        require_text("reason", self.reason, MAX_REASON_LENGTH)
