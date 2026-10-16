"""Frozen value types of the analyst. Values are canonical Decimal strings or "Unavailable"; floats are rejected."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

UNAVAILABLE = "Unavailable"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-blank text without NUL")
    return value


def _plain_date(name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{name} must be a date, not a datetime or text")
    return value


@dataclass(frozen=True)
class Fact:
    """One deterministic tool output. `value` is a Decimal string or "Unavailable"; never a float."""

    name: str
    value: str
    source: str
    as_of: date
    unit: str = ""

    def __post_init__(self) -> None:
        _text("name", self.name)
        _text("source", self.source)
        if not isinstance(self.value, str):
            raise TypeError("fact value must be text (a canonical decimal string or 'Unavailable')")
        if self.value != UNAVAILABLE:
            try:
                finite = Decimal(self.value).is_finite()
            except InvalidOperation:
                finite = False
            if not finite:
                raise ValueError("fact value must be a finite decimal string or 'Unavailable'")
        _plain_date("as_of", self.as_of)
        if not isinstance(self.unit, str):
            raise TypeError("unit must be text")

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "source": self.source, "as_of": self.as_of.isoformat(),
                "unit": self.unit}


@dataclass(frozen=True)
class Passage:
    """A retrieved document chunk that passed the date cutoff."""

    chunk_id: str
    source_id: str
    text: str
    published_at: datetime


@dataclass(frozen=True)
class Claim:
    """A number the draft states: its value text and the fact name or chunk id it comes from."""

    value: str
    source: str


@dataclass(frozen=True)
class Draft:
    text: str
    claims: tuple[Claim, ...] = ()


@dataclass(frozen=True)
class Citation:
    kind: str  # "tool" or "chunk"
    ref: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True)
class AnalystAnswer:
    text: str
    citations: tuple[Citation, ...]
    verified: bool
    as_of: date
    attempts: int

    def to_dict(self) -> dict:
        return {"text": self.text, "citations": [c.to_dict() for c in self.citations], "verified": self.verified,
                "as_of": self.as_of.isoformat(), "attempts": self.attempts}
