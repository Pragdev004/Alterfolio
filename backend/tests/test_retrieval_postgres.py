"""Feature 009 step 6: retrieval on live PostgreSQL + pgvector (spec sections 3, 6-9). Authoritative for vector behaviour.

Skipped unless ALTERFOLIO_TEST_DATABASE_URL points at an EMPTY throwaway database with `vector` already installed; the module
migrates up and back down to base and never creates or drops the extension. The end-to-end test also needs
ALTERFOLIO_TEST_OLLAMA_URL. A skipped run is not verification.
"""
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.retrieval import EMBEDDING_DIMENSION, ChunkInput, CutoffAudit, SearchResult
from app.providers.embedding.ollama import CONFIG_ID as OLLAMA_CONFIG_ID, MODEL_TAG, OllamaEmbedder
from app.repositories.chunks import ChunkRepository, NewChunk, encode_vector
from app.repositories.user_repository import UserRepository
from app.services.retrieval import RetrievalService
from tests.conftest import USER_A, USER_B
from tests.live_pg_helpers import embedding_column_type, require_safe_target, require_vector, vector_installed
from tests.test_embedding_live import OLLAMA_URL
from tests.test_migration import LIVE_URL, alembic_config, live_only, require_empty_database
from tests.test_retrieval_service import Embedder768

pytestmark = live_only

UTC = timezone.utc
CUTOFF = datetime(2026, 3, 31, 15, 30, 0, 500000, tzinfo=UTC)
LATE = CUTOFF + timedelta(microseconds=1)
EARLY = CUTOFF - timedelta(days=30)
EARLIER = EARLY - timedelta(days=30)
NOW = datetime(2026, 4, 1, tzinfo=UTC)
MIN_UTC = datetime(1, 1, 1, tzinfo=UTC)
MAX_UTC = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
CONFIG = "c" * 64


def basis(i: int, sign: float = 1.0) -> tuple[float, ...]:
    return tuple(sign if j == i else 0.0 for j in range(EMBEDDING_DIMENSION))


def mix(weight: float) -> tuple[float, ...]:
    """e0 + weight * e1: its cosine distance to e0 grows with weight."""
    return tuple(1.0 if j == 0 else weight if j == 1 else 0.0 for j in range(EMBEDDING_DIMENSION))


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(LIVE_URL)
    cfg = alembic_config()
    with engine.begin() as conn:
        require_safe_target(conn)
        require_empty_database(conn)
        require_vector(conn)
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE document_chunks, trades, import_batches, users CASCADE"))
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
        with engine.connect() as conn:
            assert vector_installed(conn), "the vector extension must still be installed"
        engine.dispose()


@pytest.fixture
def pg(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE document_chunks, users CASCADE"))
    with Session(pg_engine) as s:
        users = UserRepository(s)
        users.ensure(USER_A)
        users.ensure(USER_B)
        s.commit()
        yield s


def add(session, items, user=USER_A, ids=None):
    """items: (source_id, chunk_index, published_at, vector). Committed."""
    id_iter = iter(ids) if ids is not None else None
    repo = ChunkRepository(session, id_factory=(lambda: next(id_iter))) if id_iter else ChunkRepository(session)
    repo.add_chunks(
        user_id=user, chunks=[NewChunk(ChunkInput(s, i, f"text {s}/{i}", p), v) for s, i, p, v in items],
        embedding_model="live-test-model", embedding_config_id=CONFIG, embedding_dimension=EMBEDDING_DIMENSION,
        recorded_at=NOW,
    )
    session.commit()
    return repo


def keys(hits):
    return [(h.source_id, h.chunk_index) for h in hits]


# ---- schema, casts and inserts ------------------------------------------------------------------------------------------------


def test_the_schema_has_vector_768_a_btree_cutoff_index_and_no_vector_index(pg):
    assert embedding_column_type(pg.connection()) == "vector(768)"
    indexes = dict(pg.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'document_chunks'")).all())
    assert "USING btree (user_id, published_at)" in indexes["ix_document_chunks_user_published"]
    assert not any(word in d.lower() for d in indexes.values() for word in ("hnsw", "ivfflat"))


def test_inserted_vectors_equal_their_encoded_float32_text(pg):
    v = mix(0.123456789)
    add(pg, [("doc", 0, EARLY, v)])
    same = pg.execute(text("SELECT embedding = CAST(:v AS vector(768)) FROM document_chunks"), {"v": encode_vector(v)})
    assert same.scalar_one() is True


def test_postgres_rejects_a_vector_of_another_dimension(pg):
    short = "[" + ",".join(["0.5"] * 767) + "]"
    with pytest.raises(DBAPIError):
        pg.execute(text(
            "INSERT INTO document_chunks (id, user_id, source_id, chunk_index, text, content_sha256, published_at, "
            "recorded_at, embedding, embedding_model, embedding_config_id, embedding_dimension) VALUES (gen_random_uuid(), "
            ":u, 's', 0, 't', :h, :p, :p, CAST(:v AS vector), 'm', :h, 768)"
        ), {"u": USER_A, "h": "a" * 64, "p": EARLY, "v": short})
    pg.rollback()


# ---- distance, ranking and tie order -----------------------------------------------------------------------------------------


def test_cosine_distances_and_ranking(pg):
    repo = add(pg, [("opposite", 0, EARLY, basis(0, -1.0)), ("orthogonal", 0, EARLY, basis(1)), ("same", 0, EARLY, basis(0))])
    hits = repo.search(user_id=USER_A, query=basis(0), cutoff=CUTOFF, k=3)
    assert keys(hits) == [("same", 0), ("orthogonal", 0), ("opposite", 0)]
    assert [round(h.distance, 6) for h in hits] == [0.0, 1.0, 2.0]


def test_equal_distances_follow_the_fixed_tie_order_with_code_point_source_ids(pg):
    v = basis(3)
    ids = [UUID(int=n) for n in (6, 5, 4, 3, 2, 1)]  # ids never decide here: (source_id, chunk_index) is unique per user
    repo = add(pg, [("b", 0, EARLY, v), ("a", 1, EARLY, v), ("B", 0, EARLY, v), ("a", 0, EARLY, v), ("Z", 0, EARLIER, v),
                    ("A", 0, EARLY, v)], ids=ids)
    expected = [("Z", 0), ("A", 0), ("B", 0), ("a", 0), ("a", 1), ("b", 0)]  # published_at, then "A" < "B" < "a" < "b"
    first = repo.search(user_id=USER_A, query=v, cutoff=CUTOFF, k=50)
    assert keys(first) == expected
    assert repo.search(user_id=USER_A, query=v, cutoff=CUTOFF, k=50) == first
    assert [h.chunk_id for h in repo.nearest(user_id=USER_A, query=v, k=50)] == [h.chunk_id for h in first]


# ---- cutoff before ranking, isolation ------------------------------------------------------------------------------------------


def test_the_cutoff_is_inclusive_and_applied_before_ranking(pg):
    repo = add(pg, [("late", 0, LATE, basis(0)), ("at", 0, CUTOFF, mix(0.1)), ("c2", 0, EARLY, mix(0.2)),
                    ("c3", 0, EARLY, mix(0.3)), ("far", 0, EARLY, basis(1))])
    assert keys(repo.search(user_id=USER_A, query=basis(0), cutoff=CUTOFF, k=3)) == [("at", 0), ("c2", 0), ("c3", 0)]
    assert [h.published_at for h in repo.nearest(user_id=USER_A, query=basis(0), k=2)] == [LATE, CUTOFF]
    assert keys(repo.search(user_id=USER_A, query=basis(0), cutoff=LATE, k=1)) == [("late", 0)]
    counts = repo.counts(user_id=USER_A, cutoff=CUTOFF)
    assert (counts.total, counts.eligible, counts.excluded_after_cutoff) == (5, 4, 1)


def test_search_nearest_and_counts_are_user_scoped(pg):
    add(pg, [("mine", 0, EARLY, mix(0.5))], user=USER_A)
    repo = add(pg, [("theirs", 0, EARLY, basis(0))], user=USER_B)
    assert keys(repo.search(user_id=USER_A, query=basis(0), cutoff=CUTOFF, k=50)) == [("mine", 0)]
    assert len(repo.nearest(user_id=USER_A, query=basis(0), k=50)) == 1
    assert repo.counts(user_id=USER_B, cutoff=CUTOFF).total == 1


# ---- the service on PostgreSQL ---------------------------------------------------------------------------------------------------


def seed_service(pg, embedder):
    svc = RetrievalService(pg, ChunkRepository(pg), embedder, clock=lambda: NOW)
    svc.ingest(user_id=USER_A, chunks=[
        ChunkInput("doc-1", 0, "Early filing.", EARLY), ChunkInput("doc-2", 0, "Filed at the cutoff.", CUTOFF),
        ChunkInput("doc-3", 0, "Late filing.", LATE),
    ])
    return svc


def test_service_search_and_audit_on_postgres(pg):
    svc = seed_service(pg, Embedder768())
    result = svc.search(user_id=USER_A, query_text="Early filing.", cutoff=CUTOFF, k=50)
    assert isinstance(result, SearchResult) and [c.rank for c in result.chunks] == [1, 2]
    assert result.chunks[0].source_id == "doc-1" and math.isclose(result.chunks[0].score, 1.0, abs_tol=1e-6)
    assert {c.source_id for c in result.chunks} == {"doc-1", "doc-2"}
    assert svc.search(user_id=USER_A, query_text="Early filing.", cutoff=CUTOFF, k=50).to_dict() == result.to_dict()
    audit = svc.audit_cutoff(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=2)
    assert audit == CutoffAudit(cutoff=CUTOFF, total=3, eligible=2, excluded_after_cutoff=1, returned=2, violations=0,
                                unfiltered_top_k_after_cutoff=1)


@pytest.mark.skipif(not OLLAMA_URL, reason="no live Ollama configured (ALTERFOLIO_TEST_OLLAMA_URL)")
def test_end_to_end_with_the_real_model(pg):
    svc = seed_service(pg, OllamaEmbedder(base_url=OLLAMA_URL))
    stored = ChunkRepository(pg).get(user_id=USER_A, source_id="doc-1", chunk_index=0)
    assert (stored.embedding_model, stored.embedding_config_id) == (MODEL_TAG, OLLAMA_CONFIG_ID)
    result = svc.search(user_id=USER_A, query_text="Which filing came late?", cutoff=CUTOFF, k=50)
    assert isinstance(result, SearchResult) and {c.source_id for c in result.chunks} == {"doc-1", "doc-2"}
    audit = svc.audit_cutoff(user_id=USER_A, query_text="Which filing came late?", cutoff=CUTOFF, k=3)
    assert (audit.total, audit.eligible, audit.excluded_after_cutoff, audit.returned, audit.violations) == (3, 2, 1, 2, 0)


# ---- published_at edge instants under a non-UTC session time zone -----------------------------------------------------------------


EDGES = {"min": MIN_UTC, "max": MAX_UTC}


@pytest.mark.parametrize("edge", ["min", "max"])
@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/Los_Angeles"])
def test_edge_instants_round_trip_under_a_non_utc_session_time_zone(pg, zone, edge):
    """One test per zone and edge, so a failure at one boundary cannot hide the other (psycopg decodes in the session zone)."""
    engine = create_engine(LIVE_URL, connect_args={"options": f"-c timezone={zone}"})
    try:
        with Session(engine) as s:
            assert s.execute(text("SHOW TimeZone")).scalar_one() == zone
            repo = add(s, [("min", 0, MIN_UTC, basis(0)), ("max", 0, MAX_UTC, basis(1))])
            stored = repo.get(user_id=USER_A, source_id=edge, chunk_index=0)
            assert stored.published_at == EDGES[edge]
            assert stored.recorded_at == NOW
            assert repo.counts(user_id=USER_A, cutoff=MIN_UTC).eligible == 1
            assert repo.counts(user_id=USER_A, cutoff=MAX_UTC).eligible == 2
            hits = repo.search(user_id=USER_A, query=basis(0), cutoff=MAX_UTC, k=2)
            assert [h.published_at for h in hits] == [MIN_UTC, MAX_UTC]
            nearest = repo.nearest(user_id=USER_A, query=basis(0), k=2)
            assert [n.published_at for n in nearest] == [MIN_UTC, MAX_UTC]
    finally:
        engine.dispose()


# ---- cutoff x session zone x offset cutoff, sweep, user isolation (review gaps 1, 2, 3, 5) ------------------------------------------


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/Los_Angeles"])
@pytest.mark.parametrize("offset", [timezone(timedelta(hours=5, minutes=30)), timezone(timedelta(hours=-8))])
def test_search_and_counts_at_the_cutoff_hold_under_non_utc_session_zone_and_offset_cutoff(pg, zone, offset):
    engine = create_engine(LIVE_URL, connect_args={"options": f"-c timezone={zone}"})
    try:
        with Session(engine) as s:
            before, at, after = CUTOFF - timedelta(microseconds=1), CUTOFF, CUTOFF + timedelta(microseconds=1)
            repo = add(s, [("before", 0, before, mix(0.3)), ("at", 0, at, mix(0.2)), ("after", 0, after, basis(0))])
            cutoff = CUTOFF.astimezone(offset)
            assert cutoff.utcoffset() != timedelta(0)
            hits = repo.search(user_id=USER_A, query=basis(0), cutoff=cutoff, k=50)
            assert keys(hits) == [("at", 0), ("before", 0)]
            assert all(h.published_at <= CUTOFF for h in hits)
            counts = repo.counts(user_id=USER_A, cutoff=cutoff)
            assert (counts.total, counts.eligible, counts.excluded_after_cutoff) == (3, 2, 1)
            assert [n.published_at for n in repo.nearest(user_id=USER_A, query=basis(0), k=1)] == [after]
    finally:
        engine.dispose()


def test_no_search_ever_returns_a_chunk_after_its_cutoff(pg):
    import random

    rng = random.Random(20261016)
    base = datetime(2026, 1, 1, 9, 15, 0, 250000, tzinfo=UTC)
    stamps = [base, base + timedelta(microseconds=1), base + timedelta(seconds=1), base + timedelta(days=1),
              base + timedelta(days=1, microseconds=1), base + timedelta(days=40), base + timedelta(days=40, microseconds=1),
              base + timedelta(days=400)]
    svc = RetrievalService(pg, ChunkRepository(pg), Embedder768(), clock=lambda: NOW)
    svc.ingest(user_id=USER_A, chunks=[ChunkInput(f"s{i}", 0, f"text {rng.random()}", p) for i, p in enumerate(stamps)])
    cutoffs = sorted({p + d for p in stamps for d in (timedelta(microseconds=-1), timedelta(0), timedelta(microseconds=1))})
    for cutoff in cutoffs:
        expected = {f"s{i}" for i, p in enumerate(stamps) if p <= cutoff}
        result = svc.search(user_id=USER_A, query_text="what happened", cutoff=cutoff, k=50)
        if not expected:
            assert not isinstance(result, SearchResult) or result.chunks == ()
            continue
        assert isinstance(result, SearchResult)
        assert all(c.published_at <= cutoff for c in result.chunks)
        assert {c.source_id for c in result.chunks} == expected


def test_service_search_and_audit_ignore_other_users_chunks_on_postgres(pg):
    svc = seed_service(pg, Embedder768())
    other = svc.search(user_id=USER_B, query_text="Late filing.", cutoff=CUTOFF, k=5)
    assert not isinstance(other, SearchResult)  # B has no rows: Unavailable, A's rows are invisible
    svc.ingest(user_id=USER_B, chunks=[ChunkInput("b-late", 0, "Late filing.", LATE), ChunkInput("b-early", 0, "Query text", EARLY)])
    audit = svc.audit_cutoff(user_id=USER_A, query_text="Late filing.", cutoff=CUTOFF, k=2)
    assert audit == CutoffAudit(cutoff=CUTOFF, total=3, eligible=2, excluded_after_cutoff=1, returned=2, violations=0,
                                unfiltered_top_k_after_cutoff=1)
    result = svc.search(user_id=USER_A, query_text="Query text", cutoff=CUTOFF, k=50)
    assert {c.source_id for c in result.chunks} == {"doc-1", "doc-2"}
    b_audit = svc.audit_cutoff(user_id=USER_B, query_text="Query text", cutoff=CUTOFF, k=5)
    assert (b_audit.total, b_audit.eligible, b_audit.excluded_after_cutoff) == (2, 1, 1)


def test_user_scoped_search_never_returns_the_other_users_late_or_early_rows(pg):
    add(pg, [("a-early", 0, EARLY, mix(0.4)), ("a-late", 0, LATE, mix(0.1))], user=USER_A)
    repo = add(pg, [("b-early", 0, EARLY, basis(0)), ("b-at", 0, CUTOFF, basis(0)), ("b-late", 0, LATE, basis(0))], user=USER_B)
    assert keys(repo.search(user_id=USER_A, query=basis(0), cutoff=CUTOFF, k=50)) == [("a-early", 0)]
    assert keys(repo.search(user_id=USER_A, query=basis(0), cutoff=LATE, k=50)) == [("a-late", 0), ("a-early", 0)]
    assert keys(repo.search(user_id=USER_B, query=basis(0), cutoff=CUTOFF, k=50))[0][0].startswith("b-")
    assert all(k[0].startswith("b-") for k in keys(repo.search(user_id=USER_B, query=basis(0), cutoff=LATE, k=50)))
