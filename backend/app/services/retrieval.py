"""Feature 009 retrieval service: ingest dated chunks, cutoff-safe search and the cutoff audit (spec sections 3, 4, 6-8).

- Every input is validated (caps included) before any provider or database call; over-cap text is never sent.
- Ingest is all-or-nothing: one embedding request for the whole call, and any validation, embedding or persistence failure
  stores nothing. A provider failure is returned as `Unavailable`; nothing is retried, shortened or dropped.
- The cutoff is applied in SQL before ranking (repository). Every returned row is rechecked here; a row after the cutoff
  raises `CutoffViolationError` carrying a `CutoffAudit`, and no result is returned. Rows are never silently dropped.
- The clock is never read for the cutoff; `recorded_at` comes from the injected clock, read once per ingest.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.retrieval import (
    EMBEDDING_DIMENSION,
    ChunkInput,
    CutoffAudit,
    CutoffViolationError,
    RetrievalInputError,
    RetrievalProvenance,
    RetrievedChunk,
    SearchResult,
    Unavailable,
    UnavailableReason,
    VectorExtensionMissingError,
    is_eligible,
    to_utc,
    validate_k,
    validate_text,
)
from app.providers.embedding.port import Embedder, EmbeddingBatch, EmbeddingRole
from app.repositories.chunks import AddResult, ChunkHit, ChunkRepository, CutoffCounts, NewChunk

R = UnavailableReason


def _user(user_id: object) -> UUID:
    if not isinstance(user_id, UUID):
        raise RetrievalInputError("user_id must be a UUID")
    return user_id


def _chunks(chunks: object) -> tuple[ChunkInput, ...]:
    """Every chunk revalidated (cap, NUL, blank, index, aware date) and every key unique, before the provider is called."""
    if not isinstance(chunks, (list, tuple)) or not chunks or not all(isinstance(c, ChunkInput) for c in chunks):
        raise RetrievalInputError("chunks must be a non-empty sequence of ChunkInput")
    checked = tuple(ChunkInput(c.source_id, c.chunk_index, c.text, c.published_at) for c in chunks)
    keys = [(c.source_id, c.chunk_index) for c in checked]
    if len(set(keys)) != len(keys):
        raise RetrievalInputError("a (source_id, chunk_index) appears more than once in one call")
    return checked


def _batch_problem(batch: EmbeddingBatch, count: int) -> Unavailable | None:
    """The port guarantees finite, non-zero, equal-length vectors; the service also needs the stored dimension and count."""
    if batch.dimension != EMBEDDING_DIMENSION:
        return Unavailable(R.DIMENSION_MISMATCH,
                           f"the provider returned dimension {batch.dimension}; the index stores {EMBEDDING_DIMENSION}")
    if len(batch.vectors) != count:
        return Unavailable(R.EMBEDDING_PROVIDER_UNAVAILABLE,
                           f"the provider returned {len(batch.vectors)} vectors for {count} inputs")
    return None


def input_fingerprint(*, user_id: UUID, query_text: str, cutoff: datetime, k: int, embedding_config_id: str) -> str:
    """SHA-256 of the canonical JSON (sorted keys, no whitespace) of what a search depends on."""
    inputs = {
        "user_id": str(user_id), "query_text": query_text, "cutoff": to_utc("cutoff", cutoff).isoformat(), "k": k,
        "embedding_config_id": embedding_config_id,
    }
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RetrievalService:
    def __init__(self, session: Session, repository: ChunkRepository, embedder: Embedder, *,
                 clock: Callable[[], datetime]) -> None:
        self._session = session
        self._repo = repository
        self._embedder = embedder
        self._clock = clock

    @classmethod
    def for_session(cls, session: Session, embedder: Embedder, *, clock: Callable[[], datetime]) -> "RetrievalService":
        return cls(session, ChunkRepository(session), embedder, clock=clock)

    # ---- ingest --------------------------------------------------------------------------------------------------------

    def ingest(self, *, user_id: UUID, chunks: Sequence[ChunkInput]) -> AddResult | Unavailable:
        """Embed and store every chunk, or nothing. Commits on success, rolls back on any failure.

        Raises `RetrievalInputError` (bad input, or a chunk the model rejects as too long), `ChunkConflictError`,
        `EmbeddingIncompatibleError`. Returns `Unavailable` for provider failures and a missing `vector` extension.
        """
        user_id = _user(user_id)
        items = _chunks(chunks)
        try:
            batch = self._embedder.embed([c.text for c in items], EmbeddingRole.DOCUMENT)
        except RetrievalInputError as exc:
            if len(items) == 1:
                who = f"chunk ({items[0].source_id!r}, {items[0].chunk_index})"
            else:  # one request for the whole call: the provider does not say which input it rejected
                who = f"one of the {len(items)} chunks in this call (the provider does not identify which)"
            raise RetrievalInputError(
                f"{who} was rejected by the embedding provider; nothing was stored, retried or shortened: {exc}"
            ) from exc
        if isinstance(batch, Unavailable):
            return batch
        problem = _batch_problem(batch, len(items))
        if problem is not None:
            return problem
        if batch.model is None:
            return Unavailable(R.EMBEDDING_PROVIDER_UNAVAILABLE,
                               "the embedding provider did not report its model name; nothing was stored")
        recorded_at = self._clock()
        try:
            result = self._repo.add_chunks(
                user_id=user_id, chunks=[NewChunk(c, v) for c, v in zip(items, batch.vectors)],
                embedding_model=batch.model, embedding_config_id=batch.config_id, embedding_dimension=batch.dimension,
                recorded_at=recorded_at,
            )
            self._session.commit()
        except VectorExtensionMissingError as exc:
            self._session.rollback()
            return Unavailable(R.VECTOR_EXTENSION_MISSING, str(exc))
        except BaseException:
            self._session.rollback()
            raise
        return result

    # ---- search and audit ------------------------------------------------------------------------------------------------

    def search(self, *, user_id: UUID, query_text: str, cutoff: datetime, k: int) -> SearchResult | Unavailable:
        """The k nearest chunks published at or before `cutoff`, ranked by the exact SQL distance order."""
        user_id, query_text, cutoff, k = self._request(user_id, query_text, cutoff, k)
        counts = self._repo.counts(user_id=user_id, cutoff=cutoff)
        if counts.total == 0:
            return Unavailable(R.EMPTY_INDEX, "this user has no stored chunks")
        if counts.eligible == 0:
            return Unavailable(R.NO_ELIGIBLE_CHUNKS, "no stored chunk is published at or before the cutoff")
        query = self._query_vector(user_id, query_text)
        if isinstance(query, Unavailable):
            return query
        vector, config_id = query
        try:
            hits = self._repo.search(user_id=user_id, query=vector, cutoff=cutoff, k=k)
        except VectorExtensionMissingError as exc:
            return Unavailable(R.VECTOR_EXTENSION_MISSING, str(exc))
        self._recheck(user_id, vector, cutoff, k, counts, hits)
        if not hits:
            return Unavailable(R.NO_ELIGIBLE_CHUNKS, "the search returned no chunk published at or before the cutoff")
        provenance = RetrievalProvenance(
            embedding_config_id=config_id, embedding_dimension=EMBEDDING_DIMENSION, cutoff=cutoff, k=k,
            input_fingerprint=input_fingerprint(user_id=user_id, query_text=query_text, cutoff=cutoff, k=k,
                                                embedding_config_id=config_id),
        )
        chunks = tuple(
            RetrievedChunk(h.chunk_id, h.source_id, h.chunk_index, h.text, h.published_at, 1.0 - h.distance, rank)
            for rank, h in enumerate(hits, start=1)
        )
        return SearchResult(provenance, chunks)

    def audit_cutoff(self, *, user_id: UUID, query_text: str, cutoff: datetime, k: int) -> CutoffAudit | Unavailable:
        """Exact counts for this user's data at call time (spec section 8). The cutoff-filtered search always runs, even
        with no eligible chunk, so a leaking filter is detected; any violation raises `CutoffViolationError(audit=...)`, with
        `audit=None` when the audit cannot be built. Counts and scans are separate statements, not one snapshot."""
        user_id, query_text, cutoff, k = self._request(user_id, query_text, cutoff, k)
        counts = self._repo.counts(user_id=user_id, cutoff=cutoff)
        if counts.total == 0:
            return Unavailable(R.EMPTY_INDEX, "this user has no stored chunks")
        query = self._query_vector(user_id, query_text)
        if isinstance(query, Unavailable):
            return query
        vector, _ = query
        try:
            hits = self._repo.search(user_id=user_id, query=vector, cutoff=cutoff, k=k)
        except VectorExtensionMissingError as exc:
            return Unavailable(R.VECTOR_EXTENSION_MISSING, str(exc))
        # A violation is detected from the returned rows alone and always raised; its audit is attached when it can be built
        # (and is None when the unfiltered scan or the counts cannot support one). Only a clean search reaches the scan below.
        self._recheck(user_id, vector, cutoff, k, counts, hits)
        try:
            nearest = self._repo.nearest(user_id=user_id, query=vector, k=k)
        except VectorExtensionMissingError as exc:
            return Unavailable(R.VECTOR_EXTENSION_MISSING, str(exc))
        return self._audit(cutoff, counts, hits, nearest)

    # ---- internals -------------------------------------------------------------------------------------------------------

    @staticmethod
    def _request(user_id: object, query_text: object, cutoff: object, k: object) -> tuple[UUID, str, datetime, int]:
        """All checks run before any database or provider call; over-cap query text raises and is never sent."""
        return _user(user_id), validate_text("query_text", query_text), to_utc("cutoff", cutoff), validate_k(k)

    def _query_vector(self, user_id: UUID, query_text: str) -> tuple[tuple[float, ...], str] | Unavailable:
        stored = self._repo.config_ids(user_id=user_id)
        try:
            batch = self._embedder.embed([query_text], EmbeddingRole.QUERY)
        except RetrievalInputError as exc:
            raise RetrievalInputError(f"the query was rejected by the embedding provider; nothing was shortened: {exc}") \
                from exc
        if isinstance(batch, Unavailable):
            return batch
        problem = _batch_problem(batch, 1)
        if problem is not None:
            return problem
        if stored != {batch.config_id}:
            return Unavailable(R.EMBEDDING_INCOMPATIBLE,
                               "the query embedding identity differs from the identity of this user's stored chunks")
        return batch.vectors[0], batch.config_id

    def _recheck(self, user_id: UUID, vector: tuple[float, ...], cutoff: datetime, k: int, counts: CutoffCounts,
                 hits: list[ChunkHit]) -> None:
        """Every returned row is checked against the cutoff before any result is built (spec section 3)."""
        late = sum(not is_eligible(h.published_at, cutoff) for h in hits)
        if not late:
            return
        try:
            audit = self._audit(cutoff, counts, hits, self._repo.nearest(user_id=user_id, query=vector, k=k))
        except (VectorExtensionMissingError, RetrievalInputError):
            audit = None  # the audit itself could not be built; the violation is still raised, never swallowed
        raise CutoffViolationError(f"{late} returned chunk(s) are published after the cutoff {cutoff.isoformat()}; "
                                   "no result is returned", audit=audit)

    @staticmethod
    def _audit(cutoff: datetime, counts: CutoffCounts, hits, nearest) -> CutoffAudit:
        return CutoffAudit(
            cutoff=cutoff, total=counts.total, eligible=counts.eligible,
            excluded_after_cutoff=counts.excluded_after_cutoff, returned=len(hits),
            violations=sum(not is_eligible(h.published_at, cutoff) for h in hits),
            unfiltered_top_k_after_cutoff=sum(not is_eligible(n.published_at, cutoff) for n in nearest),
        )
