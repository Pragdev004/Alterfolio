"""Feature 009 retrieval domain types (docs/specs/009-rag-date-cutoff.md sections 3, 4, 7, 8). Stdlib only.

A defect in the inputs raises `RetrievalInputError`; a valid request with no result is `Unavailable`. Nothing is repaired,
truncated or rounded: text is kept verbatim and datetimes are only normalised to UTC. The clock is never read.
"""

import hashlib
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from app.domain import limits

SCHEMA_VERSION = 1
MAX_DETAIL_LENGTH = 512
# The embedding dimension verified on 2026-10-15 (spec sections 6 and 10). The vector column and the embedding identity use it.
EMBEDDING_DIMENSION = 768
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_FLOAT32 = struct.Struct("<f")


class RetrievalError(Exception):
    """Base class for Feature 009 retrieval errors."""


class RetrievalInputError(RetrievalError, ValueError):
    """An input defect: bad text, date, k or result shape, or a chunk or query the embedding model rejected as too long."""


class ChunkConflictError(RetrievalError):
    """The same (user_id, source_id, chunk_index) was ingested before with different text."""


class EmbeddingIncompatibleError(RetrievalError):
    """The same chunk was ingested before under a different embedding identity."""


class CutoffViolationError(RetrievalError):
    """A chunk published after the cutoff reached a result. The cutoff filter is broken; rows are never silently dropped.

    When an audit detected the violation, `audit` is that `CutoffAudit`; otherwise it is None.
    """

    def __init__(self, message: str, audit: "CutoffAudit | None" = None) -> None:
        super().__init__(message)
        self.audit = audit


class VectorExtensionMissingError(RetrievalError):
    """The PostgreSQL `vector` extension is not installed. Raised by the Feature 009 migration before it creates anything
    (a migration cannot return `Unavailable`); nothing ever creates or drops the extension. The message starts with
    VECTOR_EXTENSION_MISSING."""

    def __init__(self, detail: str = "the PostgreSQL extension `vector` is not installed in this database") -> None:
        super().__init__(f"VECTOR_EXTENSION_MISSING: {detail}")


class UnavailableReason(str, Enum):
    EMBEDDING_PROVIDER_UNAVAILABLE = "EMBEDDING_PROVIDER_UNAVAILABLE"
    EMBEDDING_MODEL_MISSING = "EMBEDDING_MODEL_MISSING"
    DIMENSION_UNRESOLVED = "DIMENSION_UNRESOLVED"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    NON_FINITE_EMBEDDING = "NON_FINITE_EMBEDDING"
    EMBEDDING_INCOMPATIBLE = "EMBEDDING_INCOMPATIBLE"
    VECTOR_EXTENSION_MISSING = "VECTOR_EXTENSION_MISSING"
    EMPTY_INDEX = "EMPTY_INDEX"
    NO_ELIGIBLE_CHUNKS = "NO_ELIGIBLE_CHUNKS"


@dataclass(frozen=True)
class Unavailable:
    """A valid request that cannot produce a result. It states why; it is never an empty list posing as success."""

    reason: UnavailableReason
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reason, UnavailableReason):
            raise RetrievalInputError("reason must be an UnavailableReason")
        if not isinstance(self.detail, str) or "\x00" in self.detail or len(self.detail) > MAX_DETAIL_LENGTH:
            raise RetrievalInputError(f"detail must be text of at most {MAX_DETAIL_LENGTH} characters without NUL")

    def to_dict(self) -> dict:
        return {"reason": self.reason.value, "detail": self.detail}


def _int(name: str, value: object, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalInputError(f"{name} must be an integer")
    if value < low or (high is not None and value > high):
        bound = f"between {low} and {high}" if high is not None else f"at least {low}"
        raise RetrievalInputError(f"{name} must be {bound}")
    return value


def _string(name: str, value: object, max_length: int | None) -> str:
    """Non-blank text without NUL, encodable as UTF-8, within `max_length` characters. Returned verbatim."""
    if not isinstance(value, str):
        raise RetrievalInputError(f"{name} must be a string")
    if "\x00" in value:
        raise RetrievalInputError(f"{name} must not contain NUL characters")
    if not value.strip():
        raise RetrievalInputError(f"{name} must not be empty")
    if max_length is not None and len(value) > max_length:
        raise RetrievalInputError(f"{name} is longer than {max_length} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise RetrievalInputError(f"{name} contains characters that cannot be encoded as UTF-8") from None
    return value


def _sha256_hex(name: str, value: object) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise RetrievalInputError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def validate_text(name: str, value: object) -> str:
    """Chunk text and query text: non-blank, no NUL, at most MAX_CHUNK_TEXT_LENGTH characters. Rejected, never truncated."""
    return _string(name, value, limits.MAX_CHUNK_TEXT_LENGTH)


def validate_k(value: object) -> int:
    return _int("k", value, limits.MIN_SEARCH_K, limits.MAX_SEARCH_K)


def to_utc(name: str, value: object) -> datetime:
    """The same instant as an aware UTC datetime. Naive values and non-datetimes raise; microseconds are kept."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RetrievalInputError(f"{name} must be a timezone-aware datetime")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):  # the offset pushes the UTC instant outside years 1..9999
        raise RetrievalInputError(f"{name} is outside the supported date range once converted to UTC") from None


def content_sha256(text: str) -> str:
    """SHA-256 (lowercase hex) of the original chunk text as UTF-8. The embedding role prefix is never included."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_float32(values: Sequence[float]) -> tuple[float, ...] | None:
    """The values exactly as pgvector stores them (IEEE float32), or None if the vector cannot be stored faithfully.

    None when a value overflows float32 or is not finite once converted, or when the sum of squares of the converted values
    is zero or not representable as a finite float32 (pgvector's cosine distance would be NaN or infinite). Nothing is
    clamped or repaired. pgvector's own accumulation order is not reproduced exactly; live tests cover the real behaviour.
    """
    converted = []
    for value in values:
        try:
            single = _FLOAT32.unpack(_FLOAT32.pack(value))[0]
        except (OverflowError, struct.error, TypeError):
            return None
        if not math.isfinite(single):
            return None
        converted.append(single)
    try:
        squares = _FLOAT32.unpack(_FLOAT32.pack(math.fsum(x * x for x in converted)))[0]
    except OverflowError:
        return None
    if not math.isfinite(squares) or squares == 0:
        return None
    return tuple(converted)


def is_eligible(published_at: object, cutoff: object) -> bool:
    """Eligible iff published_at <= cutoff (inclusive). Both must be aware; a missing date is never eligible, it raises."""
    return to_utc("published_at", published_at) <= to_utc("cutoff", cutoff)


@dataclass(frozen=True)
class ChunkInput:
    """One caller-supplied dated text chunk. Validates and normalises published_at to UTC; never repairs.

    Any aware published_at whose UTC instant is representable is accepted; there is no narrower window (spec section 3).
    """

    source_id: str
    chunk_index: int
    text: str
    published_at: datetime

    def __post_init__(self) -> None:
        _string("source_id", self.source_id, limits.MAX_SOURCE_ID_LENGTH)
        _int("chunk_index", self.chunk_index, 0, limits.MAX_CHUNK_INDEX)
        validate_text("text", self.text)
        object.__setattr__(self, "published_at", to_utc("published_at", self.published_at))


@dataclass(frozen=True)
class RetrievedChunk:
    """One ranked search hit. `score` is cosine similarity (1 - distance), a display statistic; results are never re-sorted.

    The ingest length caps are not re-applied: a stored chunk stays valid if a cap is lowered later.
    """

    chunk_id: UUID
    source_id: str
    chunk_index: int
    text: str
    published_at: datetime
    score: float
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, UUID):
            raise RetrievalInputError("chunk_id must be a UUID")
        _string("source_id", self.source_id, None)
        _int("chunk_index", self.chunk_index, 0, limits.MAX_CHUNK_INDEX)
        _string("text", self.text, None)
        if not isinstance(self.score, float) or not math.isfinite(self.score):
            raise RetrievalInputError("score must be a finite float")
        _int("rank", self.rank, 1)
        object.__setattr__(self, "published_at", to_utc("published_at", self.published_at))

    def to_dict(self) -> dict:
        return {
            "chunk_id": str(self.chunk_id), "source_id": self.source_id, "chunk_index": self.chunk_index,
            "text": self.text, "published_at": self.published_at.isoformat(), "score": self.score, "rank": self.rank,
        }


@dataclass(frozen=True)
class RetrievalProvenance:
    """What a search result depends on: the embedding identity, the cutoff, k and a SHA-256 fingerprint of the inputs."""

    embedding_config_id: str
    embedding_dimension: int
    cutoff: datetime
    k: int
    input_fingerprint: str

    def __post_init__(self) -> None:
        _sha256_hex("embedding_config_id", self.embedding_config_id)
        _int("embedding_dimension", self.embedding_dimension, 1)
        validate_k(self.k)
        _sha256_hex("input_fingerprint", self.input_fingerprint)
        object.__setattr__(self, "cutoff", to_utc("cutoff", self.cutoff))

    def to_dict(self) -> dict:
        return {
            "embedding_config_id": self.embedding_config_id, "embedding_dimension": self.embedding_dimension,
            "cutoff": self.cutoff.isoformat(), "k": self.k, "input_fingerprint": self.input_fingerprint,
        }


@dataclass(frozen=True)
class SearchResult:
    """A non-empty, ranked, cutoff-safe search result. A chunk after the cutoff raises `CutoffViolationError`; an empty
    search is `Unavailable`, never an empty result.

    The chunk order is the exact SQL distance order (spec section 7) and is kept as given. Scores are display values and are
    not used to check or re-derive that order.
    """

    provenance: RetrievalProvenance
    chunks: tuple[RetrievedChunk, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, RetrievalProvenance):
            raise RetrievalInputError("provenance must be a RetrievalProvenance")
        if not isinstance(self.chunks, tuple) or not all(isinstance(c, RetrievedChunk) for c in self.chunks):
            raise RetrievalInputError("chunks must be a tuple of RetrievedChunk")
        if self.schema_version != SCHEMA_VERSION:
            raise RetrievalInputError(f"schema_version must be {SCHEMA_VERSION}")
        if not self.chunks:
            raise RetrievalInputError("an empty search is Unavailable, never an empty result")
        cutoff = self.provenance.cutoff
        for c in self.chunks:
            if c.published_at > cutoff:
                raise CutoffViolationError(
                    f"chunk ({c.source_id!r}, {c.chunk_index}) published {c.published_at.isoformat()} "
                    f"is after the cutoff {cutoff.isoformat()}"
                )
        if len(self.chunks) > self.provenance.k:
            raise RetrievalInputError(f"a result has more than k={self.provenance.k} chunks")
        if [c.rank for c in self.chunks] != list(range(1, len(self.chunks) + 1)):
            raise RetrievalInputError("ranks must be 1..n in order")
        if len({c.chunk_id for c in self.chunks}) != len(self.chunks):
            raise RetrievalInputError("a result contains a duplicate chunk_id")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "provenance": self.provenance.to_dict(),
            "chunks": [c.to_dict() for c in self.chunks],
        }


@dataclass(frozen=True)
class CutoffAudit:
    """Exact counts for one user's data at call time (spec sections 4 and 8).

    An audit can represent violations > 0 (returned chunks after the cutoff). Enforcing the guarantee is the service's job: on
    any detected violation it raises `CutoffViolationError(..., audit=this audit)` and returns no result.
    """

    cutoff: datetime
    total: int
    eligible: int
    excluded_after_cutoff: int
    returned: int
    violations: int
    unfiltered_top_k_after_cutoff: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "cutoff", to_utc("cutoff", self.cutoff))
        for name in ("total", "eligible", "excluded_after_cutoff", "returned", "violations", "unfiltered_top_k_after_cutoff"):
            _int(name, getattr(self, name), 0)
        if self.schema_version != SCHEMA_VERSION:
            raise RetrievalInputError(f"schema_version must be {SCHEMA_VERSION}")
        if self.total != self.eligible + self.excluded_after_cutoff:
            raise RetrievalInputError("total must equal eligible + excluded_after_cutoff")
        if self.violations > self.returned:
            raise RetrievalInputError("violations must not exceed returned")
        if self.returned - self.violations > self.eligible:
            raise RetrievalInputError("returned - violations must not exceed eligible")
        if self.unfiltered_top_k_after_cutoff > self.excluded_after_cutoff:
            raise RetrievalInputError("unfiltered_top_k_after_cutoff must not exceed excluded_after_cutoff")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "cutoff": self.cutoff.isoformat(), "total": self.total,
            "eligible": self.eligible, "excluded_after_cutoff": self.excluded_after_cutoff, "returned": self.returned,
            "violations": self.violations, "unfiltered_top_k_after_cutoff": self.unfiltered_top_k_after_cutoff,
        }
