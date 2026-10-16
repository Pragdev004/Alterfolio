"""Feature 009 step 4: retrieval service (spec sections 3, 4, 6-8). SQLite and fake embedders only; no network.

Ingest runs against the real chunk repository on SQLite (non-vector behaviour). Vector search is PostgreSQL-only, so search
and audit run against `ScanRepository`, a test-only stand-in that ranks in Python over the rows the real repository stored;
SQL distance, ranking, tie order and the extension check are verified live in plan step 6, never here.
"""
import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.domain.retrieval import (
    EMBEDDING_DIMENSION,
    ChunkConflictError,
    ChunkInput,
    CutoffAudit,
    CutoffViolationError,
    EmbeddingIncompatibleError,
    RetrievalInputError,
    SearchResult,
    Unavailable,
    UnavailableReason as R,
    VectorExtensionMissingError,
)
from app.models.chunk import DocumentChunk
from app.providers.embedding.ollama import CONFIG_ID as OLLAMA_CONFIG_ID, MODEL_TAG
from app.providers.embedding.port import EmbeddingBatch, EmbeddingRole, require_role, require_texts
from app.repositories.chunks import AddResult, ChunkHit, ChunkRepository, CutoffCounts, NearestHit
from app.services.retrieval import RetrievalService, input_fingerprint
from embedding_helpers import FAKE_CONFIG_ID, fake_vector
from tests.conftest import T0, USER_A, USER_B
from tests.test_embedding_ollama import Server, adapter, body

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
CUTOFF = datetime(2026, 3, 31, 15, 30, 0, 500000, tzinfo=UTC)
LATE = CUTOFF + timedelta(microseconds=1)
EARLY = CUTOFF - timedelta(days=30)
FAKE_MODEL = "fake-embedder:v1"
OTHER_CONFIG = "b" * 64
DOC, QUERY = EmbeddingRole.DOCUMENT, EmbeddingRole.QUERY


class Embedder768:
    """Port-conforming fake: one 768-value vector per text from the text alone (role-independent, so a query equal to a
    chunk's text is that chunk's nearest neighbour). Records every call; `outcome` replaces the batch."""

    def __init__(self, *, config_id=FAKE_CONFIG_ID, model=FAKE_MODEL, dimension=EMBEDDING_DIMENSION, outcome=None):
        self.config_id, self.model, self.dimension, self.outcome = config_id, model, dimension, outcome
        self.calls: list[tuple[tuple[str, ...], EmbeddingRole]] = []

    def embed(self, texts, role):
        items, role = require_texts(texts), require_role(role)
        self.calls.append((items, role))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome is not None:
            return self.outcome
        vectors = tuple(fake_vector(DOC, t, self.dimension) for t in items)
        return EmbeddingBatch(self.config_id, self.dimension, vectors, model=self.model)


def cosine_distance(a, b) -> float:
    return 1.0 - math.fsum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))


class ScanRepository(ChunkRepository):
    """Test-only stand-in for the PostgreSQL vector scan: same user filter, same inclusive cutoff, same order keys.
    `leak=True` drops the cutoff filter to simulate a broken predicate; `missing_extension=True` raises like a database
    without `vector`."""

    def __init__(self, session, *, leak=False, missing_extension=False, fail_after_insert=False, **kw):
        super().__init__(session, **kw)
        self.leak, self.missing_extension, self.fail_after_insert = leak, missing_extension, fail_after_insert
        self.vectors: dict = {}

    def add_chunks(self, *, user_id, chunks, **kw):
        if self.missing_extension:
            raise VectorExtensionMissingError()
        result = super().add_chunks(user_id=user_id, chunks=chunks, **kw)
        if self.fail_after_insert:
            raise RuntimeError("simulated failure after the rows were flushed")
        for c in chunks:
            self.vectors.setdefault((user_id, c.chunk.source_id, c.chunk.chunk_index), c.embedding)
        return result

    def _ranked(self, user_id, query, cutoff):
        if self.missing_extension:
            raise VectorExtensionMissingError()
        q = select(DocumentChunk.id, DocumentChunk.source_id, DocumentChunk.chunk_index, DocumentChunk.text,
                   DocumentChunk.published_at).where(DocumentChunk.user_id == user_id)
        if cutoff is not None:
            q = q.where(DocumentChunk.published_at <= cutoff)
        rows = [(cosine_distance(query, self.vectors[(user_id, r.source_id, r.chunk_index)]), r)
                for r in self._session.execute(q)]
        return sorted(rows, key=lambda p: (p[0], p[1].published_at, p[1].source_id, p[1].chunk_index, p[1].id))

    def search(self, *, user_id, query, cutoff, k):
        ranked = self._ranked(user_id, query, None if self.leak else cutoff)[:k]
        return [ChunkHit(r.id, r.source_id, r.chunk_index, r.text, r.published_at, d) for d, r in ranked]

    def nearest(self, *, user_id, query, k):
        return [NearestHit(r.id, r.published_at, d) for d, r in self._ranked(user_id, query, None)[:k]]


@pytest.fixture
def repo(session, id_factory):
    return ScanRepository(session, id_factory=id_factory)


def service(session, repo, embedder=None, clock=lambda: T0):
    return RetrievalService(session, repo, embedder or Embedder768(), clock=clock)


def chunk(source_id="doc-1", chunk_index=0, text="Quarterly results were published.", published_at=EARLY) -> ChunkInput:
    return ChunkInput(source_id, chunk_index, text, published_at)


def row_count(session, user=None) -> int:
    q = select(func.count(DocumentChunk.id))
    return session.scalar(q if user is None else q.where(DocumentChunk.user_id == user))


def forged(c: ChunkInput, **fields) -> ChunkInput:
    """A ChunkInput whose fields were changed after validation (frozen dataclasses can be bypassed)."""
    for name, value in fields.items():
        object.__setattr__(c, name, value)
    return c


def seed(session, repo, user=USER_A, embedder=None):
    """early (doc-1), at the cutoff exactly (doc-2), one microsecond after it (doc-3, text equal to the query below)."""
    out = service(session, repo, embedder).ingest(user_id=user, chunks=[
        chunk("doc-1", 0, "Early filing.", EARLY), chunk("doc-2", 0, "Filed at the cutoff.", CUTOFF),
        chunk("doc-3", 0, "Late filing.", LATE),
    ])
    assert out == AddResult(inserted=3, unchanged=0)


# ---- ingest ----------------------------------------------------------------------------------------------------------------


def test_ingest_embeds_once_as_documents_and_stores_the_provider_reported_identity(session, repo):
    emb = Embedder768()
    out = service(session, repo, emb).ingest(user_id=USER_A, chunks=[chunk(text="  verbatim "), chunk(chunk_index=1)])
    assert out == AddResult(inserted=2, unchanged=0)
    assert emb.calls == [(("  verbatim ", "Quarterly results were published."), DOC)]  # original text, no prefix here
    session.rollback()  # committed by the service: a rollback here removes nothing
    stored = repo.get(user_id=USER_A, source_id="doc-1", chunk_index=0)
    assert (stored.embedding_model, stored.embedding_config_id, stored.embedding_dimension) == (FAKE_MODEL, FAKE_CONFIG_ID, 768)
    assert stored.recorded_at == T0 and stored.text == "  verbatim "


def test_reingesting_the_same_chunks_is_an_idempotent_no_op(session, repo):
    svc = service(session, repo)
    svc.ingest(user_id=USER_A, chunks=[chunk(), chunk(chunk_index=1)])
    assert svc.ingest(user_id=USER_A, chunks=[chunk(), chunk(chunk_index=1)]) == AddResult(inserted=0, unchanged=2)
    assert row_count(session) == 2


def test_one_conflicting_chunk_in_a_multi_chunk_call_persists_nothing(session, repo):
    service(session, repo).ingest(user_id=USER_A, chunks=[chunk()])
    with pytest.raises(ChunkConflictError):
        service(session, repo).ingest(user_id=USER_A, chunks=[chunk("doc-2"), chunk(text="Different text.")])
    assert row_count(session) == 1 and repo.get(user_id=USER_A, source_id="doc-2", chunk_index=0) is None


def test_an_incompatible_embedding_identity_persists_nothing(session, repo):
    service(session, repo).ingest(user_id=USER_A, chunks=[chunk()])
    with pytest.raises(EmbeddingIncompatibleError):
        service(session, repo, Embedder768(config_id=OTHER_CONFIG)).ingest(user_id=USER_A, chunks=[chunk("doc-2"), chunk()])
    assert row_count(session) == 1


def test_a_failure_after_rows_were_flushed_rolls_the_whole_call_back(session, id_factory):
    repo = ScanRepository(session, id_factory=id_factory, fail_after_insert=True)
    with pytest.raises(RuntimeError, match="simulated"):
        service(session, repo).ingest(user_id=USER_A, chunks=[chunk(), chunk(chunk_index=1)])
    assert row_count(session) == 0


def test_an_over_cap_chunk_raises_before_the_embedder_and_persists_nothing(session, repo):
    with pytest.raises(RetrievalInputError, match="longer than 4000"):
        chunk(text="x" * 4001)  # cannot even be built
    emb = Embedder768()
    with pytest.raises(RetrievalInputError, match="longer than 4000"):
        service(session, repo, emb).ingest(user_id=USER_A, chunks=[chunk(), forged(chunk(chunk_index=1), text="x" * 4001)])
    assert emb.calls == [] and row_count(session) == 0


@pytest.mark.parametrize("bad", [None, datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
def test_null_naive_or_unparsed_dates_are_rejected_before_the_embedder(session, repo, bad):
    with pytest.raises(RetrievalInputError, match="published_at"):
        chunk(published_at=bad)
    emb = Embedder768()
    with pytest.raises(RetrievalInputError, match="published_at"):
        service(session, repo, emb).ingest(user_id=USER_A, chunks=[forged(chunk(), published_at=bad)])
    assert emb.calls == [] and row_count(session) == 0


@pytest.mark.parametrize("call", [
    {"user_id": "a"}, {"chunks": []}, {"chunks": chunk()}, {"chunks": [chunk(), "x"]}, {"chunks": [chunk(), chunk()]},
])
def test_invalid_ingest_arguments_raise_before_the_embedder(session, repo, call):
    emb = Embedder768()
    with pytest.raises(RetrievalInputError):
        service(session, repo, emb).ingest(**{"user_id": USER_A, "chunks": [chunk()], **call})
    assert emb.calls == []


def test_a_context_length_rejection_names_the_single_chunk_and_stores_nothing(session, repo):
    emb = Embedder768(outcome=RetrievalInputError("a DOCUMENT input exceeds the embedding model's context length"))
    with pytest.raises(RetrievalInputError, match=r"chunk \('doc-1', 0\).*context length") as info:
        service(session, repo, emb).ingest(user_id=USER_A, chunks=[chunk()])
    assert isinstance(info.value.__cause__, RetrievalInputError)
    assert len(emb.calls) == 1 and row_count(session) == 0


def test_a_rejection_in_a_multi_chunk_call_is_not_retried_shortened_or_split(session, repo):
    """One request for the whole call; the provider does not say which input failed, so no chunk is guessed."""
    emb = Embedder768(outcome=RetrievalInputError("too long"))
    texts = ["a" * 4000, "b", "c"]
    with pytest.raises(RetrievalInputError, match="one of the 3 chunks") as info:
        service(session, repo, emb).ingest(user_id=USER_A, chunks=[chunk(chunk_index=i, text=t) for i, t in enumerate(texts)])
    assert "doc-1" not in str(info.value)
    assert emb.calls == [(tuple(texts), DOC)] and row_count(session) == 0


@pytest.mark.parametrize("reason", [R.EMBEDDING_PROVIDER_UNAVAILABLE, R.EMBEDDING_MODEL_MISSING, R.DIMENSION_UNRESOLVED,
                                    R.DIMENSION_MISMATCH, R.NON_FINITE_EMBEDDING, R.EMBEDDING_INCOMPATIBLE])
def test_every_embedder_unavailable_ends_the_ingest_with_nothing_stored(session, repo, reason):
    failure = Unavailable(reason, "fake")
    emb = Embedder768(outcome=failure)
    assert service(session, repo, emb).ingest(user_id=USER_A, chunks=[chunk(), chunk(chunk_index=1)]) is failure
    assert len(emb.calls) == 1 and row_count(session) == 0


def test_a_batch_of_another_dimension_is_dimension_mismatch(session, repo):
    out = service(session, repo, Embedder768(dimension=8)).ingest(user_id=USER_A, chunks=[chunk()])
    assert isinstance(out, Unavailable) and out.reason is R.DIMENSION_MISMATCH and row_count(session) == 0


def test_a_vector_count_different_from_the_chunk_count_is_provider_unavailable(session, repo):
    batch = EmbeddingBatch(FAKE_CONFIG_ID, 768, (fake_vector(DOC, "x", 768),), model=FAKE_MODEL)
    out = service(session, repo, Embedder768(outcome=batch)).ingest(user_id=USER_A, chunks=[chunk(), chunk(chunk_index=1)])
    assert isinstance(out, Unavailable) and out.reason is R.EMBEDDING_PROVIDER_UNAVAILABLE and row_count(session) == 0


def test_a_batch_without_a_reported_model_is_never_stored_and_no_name_is_guessed(session, repo):
    out = service(session, repo, Embedder768(model=None)).ingest(user_id=USER_A, chunks=[chunk()])
    assert isinstance(out, Unavailable) and out.reason is R.EMBEDDING_PROVIDER_UNAVAILABLE
    assert "model name" in out.detail and row_count(session) == 0


def test_a_missing_vector_extension_at_ingest_is_unavailable(session, id_factory):
    repo = ScanRepository(session, id_factory=id_factory, missing_extension=True)
    out = service(session, repo).ingest(user_id=USER_A, chunks=[chunk()])
    assert isinstance(out, Unavailable) and out.reason is R.VECTOR_EXTENSION_MISSING and row_count(session) == 0


# ---- the model-name gap: the provider reports the model; existing three-field batches are unchanged --------------------------


def test_embedding_batch_model_is_optional_and_validated():
    v = (fake_vector(DOC, "x", 3),)
    assert EmbeddingBatch(FAKE_CONFIG_ID, 3, v).model is None
    assert EmbeddingBatch(FAKE_CONFIG_ID, 3, v, model=MODEL_TAG).model == MODEL_TAG
    for bad in ("", "  ", "a\x00b", "m" * 129, 3):
        with pytest.raises(RetrievalInputError, match="model"):
            EmbeddingBatch(FAKE_CONFIG_ID, 3, v, model=bad)


@pytest.mark.parametrize("length", [4000])
def test_ollama_end_to_end_reports_its_tag_and_the_prefix_is_not_counted_in_the_cap(session, repo, length):
    """Cap boundary through the real adapter (mocked HTTP): 4,000 characters are sent with the prefix added."""
    server = Server()
    svc = service(session, repo, adapter(server))
    assert svc.ingest(user_id=USER_A, chunks=[chunk(text="d" * length)]) == AddResult(inserted=1, unchanged=0)
    stored = repo.get(user_id=USER_A, source_id="doc-1", chunk_index=0)
    assert (stored.embedding_model, stored.embedding_config_id) == (MODEL_TAG, OLLAMA_CONFIG_ID)
    assert body(server.embeds()[0])["input"] == ["search_document: " + "d" * length]
    svc.search(user_id=USER_A, query_text="q" * length, cutoff=CUTOFF, k=1)
    assert body(server.embeds()[1]) == {"model": MODEL_TAG, "input": ["search_query: " + "q" * length], "truncate": False}


# ---- search ----------------------------------------------------------------------------------------------------------------


def test_search_excludes_one_microsecond_after_the_cutoff_and_includes_the_cutoff_itself(session, repo):
    seed(session, repo)
    emb = Embedder768()
    result = service(session, repo, emb).search(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=50)
    assert isinstance(result, SearchResult)
    assert {c.source_id for c in result.chunks} == {"doc-1", "doc-2"}  # the nearest chunk (doc-3) is after the cutoff
    assert emb.calls == [(("Late filing.",), QUERY)]


def test_search_result_shape_ranks_scores_and_provenance(session, repo):
    seed(session, repo)
    result = service(session, repo).search(user_id=USER_A, query_text="Early filing.", cutoff=CUTOFF.astimezone(IST), k=1)
    (top,) = result.chunks
    assert (top.source_id, top.rank, top.published_at) == ("doc-1", 1, EARLY)
    assert math.isclose(top.score, 1.0, abs_tol=1e-12)  # score = 1 - distance; the query equals the chunk text
    p = result.provenance
    assert (p.embedding_config_id, p.embedding_dimension, p.cutoff, p.k) == (FAKE_CONFIG_ID, 768, CUTOFF, 1)
    assert p.cutoff.tzinfo is UTC
    assert p.input_fingerprint == input_fingerprint(user_id=USER_A, query_text="Early filing.", cutoff=CUTOFF, k=1,
                                                    embedding_config_id=FAKE_CONFIG_ID)
    two = service(session, repo).search(user_id=USER_A, query_text="Early filing.", cutoff=CUTOFF, k=2)
    assert [c.rank for c in two.chunks] == [1, 2]
    assert [c.score for c in two.chunks] == [1.0 - h.distance for h in repo.search(
        user_id=USER_A, query=fake_vector(DOC, "Early filing.", 768), cutoff=CUTOFF, k=2)]


def test_search_is_deterministic_and_the_fingerprint_tracks_every_input(session, repo):
    seed(session, repo)
    args = {"user_id": USER_A, "query_text": "Early filing.", "cutoff": CUTOFF, "k": 2}
    first = service(session, repo).search(**args)
    assert service(session, repo).search(**args).to_dict() == first.to_dict()
    base = input_fingerprint(embedding_config_id=FAKE_CONFIG_ID, **args)
    for change in ({"user_id": USER_B}, {"query_text": "Other."}, {"cutoff": EARLY}, {"k": 3},
                   {"embedding_config_id": OTHER_CONFIG}):
        assert input_fingerprint(**{"embedding_config_id": FAKE_CONFIG_ID, **args, **change}) != base


def test_search_is_user_isolated(session, repo):
    seed(session, repo, USER_A)
    out = service(session, repo).search(user_id=USER_B, query_text="Early filing.", cutoff=CUTOFF, k=5)
    assert isinstance(out, Unavailable) and out.reason is R.EMPTY_INDEX
    service(session, repo).ingest(user_id=USER_B, chunks=[chunk("doc-b", 0, "B only.", EARLY)])
    a = service(session, repo).search(user_id=USER_A, query_text="B only.", cutoff=CUTOFF, k=50)
    b = service(session, repo).search(user_id=USER_B, query_text="Early filing.", cutoff=CUTOFF, k=50)
    assert {c.source_id for c in a.chunks} == {"doc-1", "doc-2"} and [c.source_id for c in b.chunks] == ["doc-b"]


def test_a_leaking_filter_raises_with_the_audit_and_returns_nothing(session, id_factory):
    repo = ScanRepository(session, id_factory=id_factory, leak=True)
    seed(session, repo)
    with pytest.raises(CutoffViolationError) as info:
        service(session, repo).search(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=3)
    audit = info.value.audit
    assert isinstance(audit, CutoffAudit)
    assert (audit.total, audit.eligible, audit.excluded_after_cutoff, audit.returned, audit.violations,
            audit.unfiltered_top_k_after_cutoff) == (3, 2, 1, 3, 1, 1)


@pytest.mark.parametrize("reason", [R.EMBEDDING_PROVIDER_UNAVAILABLE, R.EMBEDDING_MODEL_MISSING, R.DIMENSION_UNRESOLVED,
                                    R.DIMENSION_MISMATCH, R.NON_FINITE_EMBEDDING, R.EMBEDDING_INCOMPATIBLE])
def test_every_embedder_unavailable_is_returned_by_search(session, repo, reason):
    seed(session, repo)
    failure = Unavailable(reason, "fake")
    assert service(session, repo, Embedder768(outcome=failure)).search(
        user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1) is failure


@pytest.mark.parametrize("embedder,reason", [
    (Embedder768(config_id=OTHER_CONFIG), R.EMBEDDING_INCOMPATIBLE), (Embedder768(dimension=8), R.DIMENSION_MISMATCH),
])
def test_a_query_embedding_that_does_not_match_the_index_is_unavailable(session, repo, embedder, reason):
    seed(session, repo)
    out = service(session, repo, embedder).search(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is reason


def test_empty_index_and_no_eligible_chunks_never_call_the_embedder(session, repo):
    emb = Embedder768()
    out = service(session, repo, emb).search(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.EMPTY_INDEX
    service(session, repo).ingest(user_id=USER_A, chunks=[chunk(published_at=LATE)])
    out = service(session, repo, emb).search(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.NO_ELIGIBLE_CHUNKS
    assert emb.calls == []


def test_a_missing_vector_extension_at_search_is_unavailable(session, id_factory):
    seed(session, ScanRepository(session, id_factory=id_factory))
    repo = ScanRepository(session, missing_extension=True)
    out = service(session, repo).search(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.VECTOR_EXTENSION_MISSING


def test_query_cap_boundary_4000_is_sent_and_4001_raises_before_the_embedder(session, repo):
    seed(session, repo)
    emb = Embedder768()
    assert isinstance(service(session, repo, emb).search(user_id=USER_A, query_text="q" * 4000, cutoff=CUTOFF, k=1),
                      SearchResult)
    assert emb.calls == [(("q" * 4000,), QUERY)]
    with pytest.raises(RetrievalInputError, match="longer than 4000"):
        service(session, repo, emb).search(user_id=USER_A, query_text="q" * 4001, cutoff=CUTOFF, k=1)
    assert len(emb.calls) == 1


def test_a_query_context_length_rejection_raises_naming_the_query(session, repo):
    seed(session, repo)
    emb = Embedder768(outcome=RetrievalInputError("a QUERY input exceeds the embedding model's context length"))
    with pytest.raises(RetrievalInputError, match="the query.*context length"):
        service(session, repo, emb).search(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert len(emb.calls) == 1


@pytest.mark.parametrize("call", [
    {"user_id": None}, {"query_text": ""}, {"query_text": "a\x00"}, {"query_text": 3}, {"cutoff": datetime(2026, 3, 31)},
    {"cutoff": None}, {"k": 0}, {"k": 51}, {"k": True},
])
def test_invalid_search_and_audit_arguments_raise_before_any_call(session, repo, call):
    seed(session, repo)
    emb = Embedder768()
    args = {"user_id": USER_A, "query_text": "q", "cutoff": CUTOFF, "k": 1, **call}
    for method in ("search", "audit_cutoff"):
        with pytest.raises(RetrievalInputError):
            getattr(service(session, repo, emb), method)(**args)
    assert emb.calls == []


# ---- audit -----------------------------------------------------------------------------------------------------------------


def test_audit_counts_are_exact(session, repo):
    seed(session, repo)
    audit = service(session, repo).audit_cutoff(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=2)
    assert audit == CutoffAudit(cutoff=CUTOFF, total=3, eligible=2, excluded_after_cutoff=1, returned=2, violations=0,
                                unfiltered_top_k_after_cutoff=1)
    at_late = service(session, repo).audit_cutoff(user_id=USER_A, query_text="Late filing.", cutoff=LATE, k=3)
    assert (at_late.eligible, at_late.excluded_after_cutoff, at_late.returned) == (3, 0, 3)


def test_audit_with_no_eligible_chunk_still_runs_the_filtered_search(session, repo):
    seed(session, repo)
    audit = service(session, repo).audit_cutoff(user_id=USER_A, query_text="q", cutoff=EARLY - timedelta(days=1), k=5)
    assert (audit.total, audit.eligible, audit.returned, audit.violations, audit.unfiltered_top_k_after_cutoff) == (3, 0, 0, 0, 3)


def test_audit_raises_carrying_the_audit_when_the_filter_leaks(session, id_factory):
    repo = ScanRepository(session, id_factory=id_factory, leak=True)
    seed(session, repo)
    with pytest.raises(CutoffViolationError) as info:
        service(session, repo).audit_cutoff(user_id=USER_A, query_text="q", cutoff=EARLY - timedelta(days=1), k=5)
    audit = info.value.audit
    assert (audit.eligible, audit.returned, audit.violations) == (0, 3, 3)


def test_audit_unavailable_cases(session, repo):
    out = service(session, repo).audit_cutoff(user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.EMPTY_INDEX
    seed(session, repo)
    out = service(session, repo, Embedder768(config_id=OTHER_CONFIG)).audit_cutoff(
        user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.EMBEDDING_INCOMPATIBLE
    out = service(session, ScanRepository(session, missing_extension=True)).audit_cutoff(
        user_id=USER_A, query_text="q", cutoff=CUTOFF, k=1)
    assert isinstance(out, Unavailable) and out.reason is R.VECTOR_EXTENSION_MISSING


# ---- a detected violation is always raised, even when the audit cannot be built (spec section 4) -------------------------------


class FaultyScanRepository(ScanRepository):
    """`stale_counts` reports one fewer eligible chunk than the scan returns (rows written between the statements);
    `nearest_missing_extension` makes only the unfiltered scan raise like a database without `vector`."""

    def __init__(self, session, *, stale_counts=False, nearest_missing_extension=False, **kw):
        super().__init__(session, **kw)
        self.stale_counts, self.nearest_missing_extension = stale_counts, nearest_missing_extension

    def counts(self, **kw):
        real = super().counts(**kw)
        if not self.stale_counts:
            return real
        return CutoffCounts(real.total, real.eligible - 1, real.excluded_after_cutoff + 1)

    def nearest(self, **kw):
        if self.nearest_missing_extension:
            raise VectorExtensionMissingError()
        return super().nearest(**kw)


@pytest.mark.parametrize("fault", ["stale_counts", "nearest_missing_extension"])
@pytest.mark.parametrize("method", ["search", "audit_cutoff"])
def test_a_detected_violation_raises_with_audit_none_when_the_audit_cannot_be_built(session, id_factory, method, fault):
    repo = FaultyScanRepository(session, id_factory=id_factory, leak=True, **{fault: True})
    seed(session, repo)
    with pytest.raises(CutoffViolationError) as info:
        getattr(service(session, repo), method)(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=3)
    assert info.value.audit is None
    assert "1 returned chunk(s) are published after the cutoff" in str(info.value)


def test_without_a_violation_a_missing_extension_on_the_unfiltered_scan_stays_unavailable(session, id_factory):
    repo = FaultyScanRepository(session, id_factory=id_factory, nearest_missing_extension=True)
    seed(session, repo)
    out = service(session, repo).audit_cutoff(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=3)
    assert isinstance(out, Unavailable) and out.reason is R.VECTOR_EXTENSION_MISSING


# ---- review gaps: audit user scope, cutoff sweep ----------------------------------------------------------------------------------


def test_audit_counts_are_user_scoped(session, repo):
    seed(session, repo, USER_A)
    out = service(session, repo).audit_cutoff(user_id=USER_B, query_text="Late filing.", cutoff=CUTOFF, k=3)
    assert isinstance(out, Unavailable) and out.reason is R.EMPTY_INDEX
    service(session, repo).ingest(user_id=USER_B, chunks=[chunk("doc-b", 0, "B only.", EARLY), chunk("doc-b", 1, "B late.", LATE)])
    a = service(session, repo).audit_cutoff(user_id=USER_A, query_text="B only.", cutoff=CUTOFF, k=5)
    b = service(session, repo).audit_cutoff(user_id=USER_B, query_text="B only.", cutoff=CUTOFF, k=5)
    assert (a.total, a.eligible, a.excluded_after_cutoff) == (3, 2, 1)
    assert (b.total, b.eligible, b.excluded_after_cutoff) == (2, 1, 1)


def test_no_search_returns_a_chunk_dated_after_any_swept_cutoff(session, repo):
    stamps = [CUTOFF + d for d in (timedelta(days=-9), timedelta(microseconds=-1), timedelta(0), LATE - CUTOFF,
                                    timedelta(seconds=1), timedelta(days=3))]
    service(session, repo).ingest(user_id=USER_A, chunks=[chunk(f"s{i}", 0, f"text {i}", p) for i, p in enumerate(stamps)])
    for cutoff in sorted({p + d for p in stamps for d in (timedelta(microseconds=-1), timedelta(0), timedelta(microseconds=1))}):
        expected = {f"s{i}" for i, p in enumerate(stamps) if p <= cutoff}
        out = service(session, repo).search(user_id=USER_A, query_text="text 3", cutoff=cutoff, k=50)
        if not expected:
            assert not isinstance(out, SearchResult) or out.chunks == ()
            continue
        assert all(c.published_at <= cutoff for c in out.chunks)
        assert {c.source_id for c in out.chunks} == expected
