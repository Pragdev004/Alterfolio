"""Feature 009 chunk repository (spec sections 3, 6, 7). Every method is user-scoped; storage is append-only.

- Writes never commit: the caller owns the transaction, so an ingest call is all-or-nothing. Every row is checked before
  anything is written, and a conflicting or incompatible row raises before any insert.
- Vectors are written as float32-checked `[v1,...]` text, cast to `vector(D)` by PostgreSQL. The vector column is never read
  back. Distances come from `<=>` in SQL.
- Vector search runs only on PostgreSQL with pgvector (authoritative); SQLite is test-only and refuses vector queries.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import bindparam, case, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.types import Float, Integer, String, Uuid

from app.db.portable_types import UTCDateTime
from app.domain import limits
from app.domain.retrieval import (
    EMBEDDING_DIMENSION,
    ChunkConflictError,
    ChunkInput,
    EmbeddingIncompatibleError,
    RetrievalInputError,
    VectorExtensionMissingError,
    as_float32,
    content_sha256,
    to_utc,
    validate_k,
)
from app.models.chunk import DocumentChunk

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# Exact cosine scan (no vector index). The predicate is in WHERE, before ranking; the tie order is fixed (spec section 7).
# `COLLATE "C"` orders source_id by code point, so the order does not depend on the database's default collation.
_ORDER = 'ORDER BY distance ASC, published_at ASC, source_id COLLATE "C" ASC, chunk_index ASC, id ASC'
# The UTC wall clock, so the driver never converts an edge instant into the session time zone (see `ChunkUTCDateTime`).
_PUBLISHED_UTC = "timezone('UTC', published_at) AS published_at"
_DISTANCE = f"embedding <=> CAST(:query AS vector({EMBEDDING_DIMENSION})) AS distance"
SEARCH_SQL = text(
    f"SELECT id, source_id, chunk_index, text, {_PUBLISHED_UTC}, {_DISTANCE} FROM document_chunks "
    f"WHERE user_id = :user_id AND published_at <= :cutoff {_ORDER} LIMIT :k"
)
# The same scan without the cutoff predicate, for the audit's unfiltered top-k (spec section 8).
NEAREST_SQL = text(f"SELECT id, {_PUBLISHED_UTC}, {_DISTANCE} FROM document_chunks WHERE user_id = :user_id {_ORDER} LIMIT :k")
_BIND_TYPES = {"user_id": Uuid(), "cutoff": UTCDateTime(), "query": String(), "k": Integer()}


def _bound(statement, names):
    return statement.bindparams(*(bindparam(name, type_=_BIND_TYPES[name]) for name in names))


_SEARCH = _bound(SEARCH_SQL, ("query", "user_id", "cutoff", "k")).columns(
    id=Uuid(), source_id=String(), chunk_index=Integer(), text=String(), published_at=UTCDateTime(), distance=Float()
)
_NEAREST = _bound(NEAREST_SQL, ("query", "user_id", "k")).columns(id=Uuid(), published_at=UTCDateTime(), distance=Float())


def encode_vector(values: Sequence[float]) -> str:
    """`[v1,...]` text of the float32 values pgvector will store; raises rather than clamping or repairing anything."""
    if not isinstance(values, (tuple, list)) or len(values) != EMBEDDING_DIMENSION:
        raise RetrievalInputError(f"a vector must hold exactly {EMBEDDING_DIMENSION} values")
    if not all(isinstance(v, float) for v in values):
        raise RetrievalInputError("a vector must hold floats only")
    single = as_float32(values)
    if single is None:
        raise RetrievalInputError("NON_FINITE_EMBEDDING: the vector is not finite with a non-zero norm as float32")
    return "[" + ",".join(repr(v) for v in single) + "]"


@dataclass(frozen=True)
class NewChunk:
    """One chunk to store, with its embedding as returned by the embedding port."""

    chunk: ChunkInput
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class StoredChunk:
    """A stored row's identity and provenance. Never the vector."""

    id: UUID
    source_id: str
    chunk_index: int
    text: str
    content_sha256: str
    published_at: datetime
    recorded_at: datetime
    embedding_model: str
    embedding_config_id: str
    embedding_dimension: int


@dataclass(frozen=True)
class AddResult:
    inserted: int
    unchanged: int  # idempotent no-ops: same key, same text and date, same embedding identity


@dataclass(frozen=True)
class CutoffCounts:
    total: int
    eligible: int
    excluded_after_cutoff: int


@dataclass(frozen=True)
class ChunkHit:
    """One row of a vector search, in SQL order. `distance` is pgvector's cosine distance."""

    chunk_id: UUID
    source_id: str
    chunk_index: int
    text: str
    published_at: datetime
    distance: float


@dataclass(frozen=True)
class NearestHit:
    chunk_id: UUID
    published_at: datetime
    distance: float


_STORED_COLUMNS = (
    DocumentChunk.id, DocumentChunk.source_id, DocumentChunk.chunk_index, DocumentChunk.text, DocumentChunk.content_sha256,
    DocumentChunk.published_at, DocumentChunk.recorded_at, DocumentChunk.embedding_model, DocumentChunk.embedding_config_id,
    DocumentChunk.embedding_dimension,
)


class ChunkRepository:
    """Append-only, user-scoped storage of dated chunks. There is no update and no delete."""

    def __init__(self, session: Session, *, id_factory=uuid4) -> None:
        self._session = session
        self._id_factory = id_factory

    # ---- reads (never the vector) ----------------------------------------------------------------------------------------

    def get(self, *, user_id: UUID, source_id: str, chunk_index: int) -> StoredChunk | None:
        row = self._session.execute(
            select(*_STORED_COLUMNS).where(
                DocumentChunk.user_id == user_id, DocumentChunk.source_id == source_id,
                DocumentChunk.chunk_index == chunk_index,
            )
        ).one_or_none()
        return StoredChunk(*row) if row is not None else None

    def config_ids(self, *, user_id: UUID) -> frozenset[str]:
        """The embedding identities in this user's index (at most one when a user's ingests are serialised; concurrent ingests are unsupported, spec section 8)."""
        return frozenset(self._session.scalars(
            select(DocumentChunk.embedding_config_id).where(DocumentChunk.user_id == user_id).distinct()
        ))

    def counts(self, *, user_id: UUID, cutoff: datetime) -> CutoffCounts:
        """Exact counts for this user at call time: eligible iff published_at <= cutoff (inclusive)."""
        cutoff = to_utc("cutoff", cutoff)
        total, eligible = self._session.execute(
            select(
                func.count(DocumentChunk.id),
                func.coalesce(func.sum(case((DocumentChunk.published_at <= cutoff, 1), else_=0)), 0),
            ).where(DocumentChunk.user_id == user_id)
        ).one()
        return CutoffCounts(total, eligible, total - eligible)

    # ---- writes ------------------------------------------------------------------------------------------------------------

    def add_chunks(
        self, *, user_id: UUID, chunks: Sequence[NewChunk], embedding_model: str, embedding_config_id: str,
        embedding_dimension: int, recorded_at: datetime,
    ) -> AddResult:
        """Insert new chunks; same key with the same text, date and identity is a no-op (spec section 6).

        Raises before writing anything: `ChunkConflictError` for the same key with different text or date,
        `EmbeddingIncompatibleError` for the same chunk under another identity or a user index that would mix identities,
        `RetrievalInputError` for invalid arguments (a key repeated in one call, a bad vector or identity).
        Does not commit; the caller's transaction makes the whole call all-or-nothing.
        """
        if not isinstance(chunks, (list, tuple)) or not chunks or not all(isinstance(c, NewChunk) for c in chunks):
            raise RetrievalInputError("chunks must be a non-empty sequence of NewChunk")
        if not isinstance(embedding_config_id, str) or not _SHA256_HEX.fullmatch(embedding_config_id):
            raise RetrievalInputError("embedding_config_id must be 64 lowercase hexadecimal characters")
        if embedding_dimension != EMBEDDING_DIMENSION or isinstance(embedding_dimension, bool):
            raise RetrievalInputError(f"embedding_dimension must be {EMBEDDING_DIMENSION} (the vector column's dimension)")
        if (not isinstance(embedding_model, str) or not embedding_model.strip() or "\x00" in embedding_model
                or len(embedding_model) > limits.MAX_EMBEDDING_MODEL_LENGTH):
            raise RetrievalInputError(f"embedding_model must be non-blank text of at most {limits.MAX_EMBEDDING_MODEL_LENGTH}")
        recorded_at = to_utc("recorded_at", recorded_at)
        keys = [(c.chunk.source_id, c.chunk.chunk_index) for c in chunks]
        if len(set(keys)) != len(keys):
            raise RetrievalInputError("a (source_id, chunk_index) appears more than once in one call")
        encoded = [encode_vector(c.embedding) for c in chunks]  # every vector is checked before any write

        existing = {
            (row.source_id, row.chunk_index): row
            for row in (StoredChunk(*r) for r in self._session.execute(
                select(*_STORED_COLUMNS).where(
                    DocumentChunk.user_id == user_id, DocumentChunk.source_id.in_({k[0] for k in keys})
                )
            ))
        }
        fresh: list[tuple[NewChunk, str]] = []
        unchanged = 0
        for new, vector in zip(chunks, encoded):
            stored = existing.get((new.chunk.source_id, new.chunk.chunk_index))
            if stored is None:
                fresh.append((new, vector))
                continue
            if stored.content_sha256 != content_sha256(new.chunk.text) or stored.published_at != new.chunk.published_at:
                raise ChunkConflictError(
                    f"chunk ({new.chunk.source_id!r}, {new.chunk.chunk_index}) is already stored with different text or "
                    "published_at; storage is append-only"
                )
            if stored.embedding_config_id != embedding_config_id:
                raise EmbeddingIncompatibleError(
                    f"chunk ({new.chunk.source_id!r}, {new.chunk.chunk_index}) is stored under another embedding identity"
                )
            unchanged += 1
        if fresh and self.config_ids(user_id=user_id) - {embedding_config_id}:
            raise EmbeddingIncompatibleError("this user's index uses another embedding identity; identities are never mixed")
        if fresh:
            self._require_vector()
            self._session.add_all([
                DocumentChunk(
                    id=self._id_factory(), user_id=user_id, source_id=new.chunk.source_id,
                    chunk_index=new.chunk.chunk_index, text=new.chunk.text, content_sha256=content_sha256(new.chunk.text),
                    published_at=new.chunk.published_at, recorded_at=recorded_at, embedding=vector,
                    embedding_model=embedding_model, embedding_config_id=embedding_config_id,
                    embedding_dimension=embedding_dimension,
                )
                for new, vector in fresh
            ])
            self._session.flush()
        return AddResult(inserted=len(fresh), unchanged=unchanged)

    # ---- vector search (PostgreSQL + pgvector only) --------------------------------------------------------------------------

    def search(self, *, user_id: UUID, query: Sequence[float], cutoff: datetime, k: int) -> list[ChunkHit]:
        """The k nearest eligible chunks (published_at <= cutoff, filtered in SQL before ranking), in the spec order."""
        params = {"query": encode_vector(query), "user_id": user_id, "cutoff": to_utc("cutoff", cutoff), "k": validate_k(k)}
        self._require_postgres()
        self._require_vector()
        return [ChunkHit(*row) for row in self._session.execute(_SEARCH, params)]

    def nearest(self, *, user_id: UUID, query: Sequence[float], k: int) -> list[NearestHit]:
        """The k nearest chunks with no cutoff filter (the audit's unfiltered top-k)."""
        params = {"query": encode_vector(query), "user_id": user_id, "k": validate_k(k)}
        self._require_postgres()
        self._require_vector()
        return [NearestHit(*row) for row in self._session.execute(_NEAREST, params)]

    def _require_postgres(self) -> None:
        if self._session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("vector search runs only on PostgreSQL with pgvector; SQLite is test-only")

    def _require_vector(self) -> None:
        if self._session.get_bind().dialect.name != "postgresql":
            return  # SQLite stores the vector as test-only TEXT
        if self._session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first() is None:
            raise VectorExtensionMissingError()
