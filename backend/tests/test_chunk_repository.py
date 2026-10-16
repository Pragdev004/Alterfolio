"""Feature 009 step 3: chunk repository on SQLite (test-only; non-vector behaviour only, spec section 6).

Vector casts, distances, ranking, tie order and the extension check are PostgreSQL-only and verified live (plan step 6).
Here the SQL text of those queries is checked statically, and SQLite must refuse to run them.
"""
import hashlib
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import TypeDecorator

from app.domain.retrieval import (
    EMBEDDING_DIMENSION,
    ChunkConflictError,
    ChunkInput,
    EmbeddingIncompatibleError,
    RetrievalInputError,
)
from app.db.portable_types import UTCDateTime
from app.models.chunk import DocumentChunk
from app.models.trade import Trade
from app.repositories.chunks import (
    NEAREST_SQL,
    SEARCH_SQL,
    AddResult,
    ChunkRepository,
    CutoffCounts,
    NewChunk,
    encode_vector,
)
from tests.conftest import USER_A, USER_B

UTC = timezone.utc
T0 = datetime(2026, 1, 15, 10, 30, 0, 123456, tzinfo=UTC)
NOW = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
CONFIG_A = hashlib.sha256(b"identity-a").hexdigest()
CONFIG_B = hashlib.sha256(b"identity-b").hexdigest()
MODEL = "nomic-embed-text:latest"


def vec(seed: int = 1) -> tuple[float, ...]:
    return tuple(((i * 7 + seed) % 13 - 6) / 8 + 0.01 for i in range(EMBEDDING_DIMENSION))


def new(source_id="doc-1", chunk_index=0, text="Quarterly results were published.", published_at=T0, seed=1) -> NewChunk:
    return NewChunk(ChunkInput(source_id, chunk_index, text, published_at), vec(seed))


@pytest.fixture
def repo(session, id_factory):
    return ChunkRepository(session, id_factory=id_factory)


def add(repo, chunks, user=USER_A, config=CONFIG_A, **kw) -> AddResult:
    fields = {"embedding_model": MODEL, "embedding_config_id": config, "embedding_dimension": EMBEDDING_DIMENSION,
              "recorded_at": NOW}
    fields.update(kw)
    return repo.add_chunks(user_id=user, chunks=chunks, **fields)


def row_count(session, user=None) -> int:
    query = select(func.count(DocumentChunk.id))
    if user is not None:
        query = query.where(DocumentChunk.user_id == user)
    return session.scalar(query)


# ---- inserts and stored identity --------------------------------------------------------------------------------------------


def test_add_stores_the_original_text_hash_dates_and_identity(repo, session):
    text_ = "  Kept verbatim.\n"
    assert add(repo, [new(text=text_)]) == AddResult(inserted=1, unchanged=0)
    stored = repo.get(user_id=USER_A, source_id="doc-1", chunk_index=0)
    assert stored.text == text_  # no role prefix, never stripped
    assert stored.content_sha256 == hashlib.sha256(text_.encode("utf-8")).hexdigest()
    assert (stored.published_at, stored.recorded_at) == (T0, NOW)
    assert stored.published_at.tzinfo is not None and stored.published_at.utcoffset() == timedelta(0)
    assert (stored.embedding_model, stored.embedding_config_id, stored.embedding_dimension) == (MODEL, CONFIG_A, 768)
    assert isinstance(stored.id, UUID)
    assert not hasattr(stored, "embedding")


def test_add_does_not_commit(repo, session):
    add(repo, [new()])
    session.rollback()
    assert row_count(session) == 0  # the caller's transaction decides: the whole call is all-or-nothing


# ---- idempotency, conflict, incompatible identity (spec section 6) ----------------------------------------------------------


def test_the_same_chunk_twice_is_an_idempotent_no_op(repo, session):
    add(repo, [new(), new(chunk_index=1, text="second")])
    assert add(repo, [new(), new(chunk_index=1, text="second")]) == AddResult(inserted=0, unchanged=2)
    assert add(repo, [new(), new(chunk_index=2, text="third")]) == AddResult(inserted=1, unchanged=1)
    assert row_count(session) == 3


def test_different_text_under_the_same_key_is_a_conflict_and_nothing_is_written(repo, session):
    add(repo, [new()])
    with pytest.raises(ChunkConflictError, match="doc-1"):
        add(repo, [new(chunk_index=5, text="new one"), new(text="changed text")])
    assert row_count(session) == 1  # the new chunk in the same call was not written either
    assert repo.get(user_id=USER_A, source_id="doc-1", chunk_index=0).text == "Quarterly results were published."


def test_a_different_published_at_under_the_same_key_is_a_conflict(repo):
    add(repo, [new()])
    with pytest.raises(ChunkConflictError):
        add(repo, [new(published_at=T0 + timedelta(microseconds=1))])


def test_the_same_text_under_another_identity_is_incompatible(repo, session):
    add(repo, [new()])
    with pytest.raises(EmbeddingIncompatibleError):
        add(repo, [new()], config=CONFIG_B)
    assert row_count(session) == 1


def test_a_user_index_never_mixes_identities(repo, session):
    add(repo, [new()])
    with pytest.raises(EmbeddingIncompatibleError, match="mixed"):
        add(repo, [new(source_id="doc-2")], config=CONFIG_B)
    assert repo.config_ids(user_id=USER_A) == frozenset({CONFIG_A})
    assert add(repo, [new(source_id="doc-2")], user=USER_B, config=CONFIG_B).inserted == 1  # another user may differ


def test_a_key_repeated_in_one_call_is_rejected_before_any_write(repo, session):
    with pytest.raises(RetrievalInputError, match="more than once"):
        add(repo, [new(), new(text="other")])
    assert row_count(session) == 0


# ---- user isolation -----------------------------------------------------------------------------------------------------------


def test_every_read_and_write_is_user_scoped(repo, session):
    add(repo, [new()])
    assert repo.get(user_id=USER_B, source_id="doc-1", chunk_index=0) is None
    assert add(repo, [new(text="B's own text")], user=USER_B) == AddResult(inserted=1, unchanged=0)  # same key, other user
    assert repo.get(user_id=USER_B, source_id="doc-1", chunk_index=0).text == "B's own text"
    assert repo.get(user_id=USER_A, source_id="doc-1", chunk_index=0).text == "Quarterly results were published."
    assert repo.counts(user_id=USER_B, cutoff=T0) == CutoffCounts(1, 1, 0)
    assert repo.config_ids(user_id=USER_B) == frozenset({CONFIG_A})
    assert (row_count(session, USER_A), row_count(session, USER_B)) == (1, 1)


# ---- cutoff counts (non-vector; spec section 3) --------------------------------------------------------------------------------


def test_counts_are_inclusive_at_the_cutoff_and_exclude_one_microsecond_later(repo):
    add(repo, [new(chunk_index=0, published_at=T0 - timedelta(days=1)), new(chunk_index=1, published_at=T0),
               new(chunk_index=2, published_at=T0 + timedelta(microseconds=1))])
    assert repo.counts(user_id=USER_A, cutoff=T0) == CutoffCounts(total=3, eligible=2, excluded_after_cutoff=1)
    assert repo.counts(user_id=USER_A, cutoff=T0 - timedelta(microseconds=1)) == CutoffCounts(3, 1, 2)
    ist = timezone(timedelta(hours=5, minutes=30))
    assert repo.counts(user_id=USER_A, cutoff=T0.astimezone(ist)) == CutoffCounts(3, 2, 1)  # same instant, other offset
    assert repo.counts(user_id=USER_B, cutoff=T0) == CutoffCounts(0, 0, 0)
    with pytest.raises(RetrievalInputError, match="cutoff"):
        repo.counts(user_id=USER_A, cutoff=datetime(2026, 1, 1))


# ---- argument and vector validation (raised before any write) -----------------------------------------------------------------


@pytest.mark.parametrize("embedding", [
    vec()[:-1], vec() + (0.5,), (math.nan,) + vec()[1:], (math.inf,) + vec()[1:], (1e39,) + vec()[1:],
    (0.0,) * EMBEDDING_DIMENSION, (1e-46,) * EMBEDDING_DIMENSION, (1,) + vec()[1:], [0.5] * 767,
])
def test_a_vector_that_float32_cannot_store_faithfully_is_rejected_before_any_write(repo, session, embedding):
    with pytest.raises(RetrievalInputError):
        add(repo, [NewChunk(ChunkInput("doc-1", 0, "text", T0), embedding)])
    assert row_count(session) == 0


@pytest.mark.parametrize("overrides", [
    {"config": "A" * 64}, {"config": "a" * 63}, {"embedding_dimension": 384}, {"embedding_dimension": True},
    {"embedding_model": ""}, {"embedding_model": "m" * 129}, {"embedding_model": "a\x00"},
    {"recorded_at": datetime(2026, 2, 1)},
])
def test_invalid_identity_or_recorded_at_is_rejected(repo, session, overrides):
    with pytest.raises(RetrievalInputError):
        add(repo, [new()], **overrides)
    assert row_count(session) == 0


@pytest.mark.parametrize("chunks", [[], (), None, [object()], "doc"])
def test_chunks_must_be_a_non_empty_sequence_of_new_chunks(repo, chunks):
    with pytest.raises(RetrievalInputError):
        add(repo, chunks)


# ---- vector encoding (float32 text for pgvector) -------------------------------------------------------------------------------


def test_encode_vector_writes_the_exact_float32_values():
    values = (0.1,) + vec()[1:]
    encoded = encode_vector(values)
    assert encoded.startswith("[0.10000000149011612,") and encoded.endswith("]")
    assert len(encoded[1:-1].split(",")) == EMBEDDING_DIMENSION
    assert "e" not in encoded[1:20] and " " not in encoded


def test_encode_vector_never_clamps_or_repairs():
    for bad in ((3.5e38,) + vec()[1:], (-1e39,) + vec()[1:], (math.nan,) + vec()[1:], (0.0,) * 768):
        with pytest.raises(RetrievalInputError):
            encode_vector(bad)


# ---- append-only and write-only vector ------------------------------------------------------------------------------------------


def test_the_repository_has_no_update_or_delete():
    public = {name for name in dir(ChunkRepository) if not name.startswith("_")}
    assert public == {"get", "config_ids", "counts", "add_chunks", "search", "nearest"}


def test_the_vector_column_is_never_read_back(repo, session):
    add(repo, [new()])
    entity = session.scalars(select(DocumentChunk)).one()
    with pytest.raises(InvalidRequestError):
        entity.embedding  # deferred with raiseload
    with pytest.raises(Exception, match="never read back"):
        session.execute(select(DocumentChunk.embedding)).all()


# ---- PostgreSQL-only vector queries: SQLite refuses; the SQL contract is checked statically ------------------------------------


def test_sqlite_refuses_vector_queries(repo):
    add(repo, [new()])
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        repo.search(user_id=USER_A, query=vec(), cutoff=T0, k=5)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        repo.nearest(user_id=USER_A, query=vec(), k=5)


def test_search_arguments_are_validated_before_the_database_is_touched(repo):
    with pytest.raises(RetrievalInputError):
        repo.search(user_id=USER_A, query=vec()[:3], cutoff=T0, k=5)
    with pytest.raises(RetrievalInputError, match="cutoff"):
        repo.search(user_id=USER_A, query=vec(), cutoff=datetime(2026, 1, 1), k=5)
    with pytest.raises(RetrievalInputError, match="k"):
        repo.search(user_id=USER_A, query=vec(), cutoff=T0, k=51)


def test_the_search_sql_filters_before_ranking_and_fixes_the_tie_order():
    sql = " ".join(str(SEARCH_SQL).split())
    where, order = sql.index("WHERE"), sql.index("ORDER BY")
    assert "user_id = :user_id AND published_at <= :cutoff" in sql[where:order]  # predicate in WHERE, before ranking
    assert sql[order:].startswith(
        'ORDER BY distance ASC, published_at ASC, source_id COLLATE "C" ASC, chunk_index ASC, id ASC LIMIT :k'
    )
    assert "embedding <=> CAST(:query AS vector(768)) AS distance" in sql
    assert sql.count("embedding") == 1  # only inside the distance expression: the vector is never selected


def test_the_unfiltered_nearest_sql_has_no_cutoff_but_is_user_scoped():
    sql = " ".join(str(NEAREST_SQL).split())
    assert "published_at <=" not in sql and "WHERE user_id = :user_id" in sql
    assert 'ORDER BY distance ASC, published_at ASC, source_id COLLATE "C" ASC, chunk_index ASC, id ASC LIMIT :k' in sql


def test_postgres_inserts_cast_the_vector_text_to_vector_768():
    statement = insert(DocumentChunk.__table__).values(id=UUID(int=1), embedding="[1.0]")
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "CAST(%(embedding)s AS vector(768))" in compiled


# ---- chunk timestamp read-back: the UTC wall clock is selected on PostgreSQL only -------------------------------------------------


def test_chunk_timestamp_columns_select_the_utc_wall_clock_on_postgresql_only():
    statement = select(DocumentChunk.published_at, DocumentChunk.recorded_at)
    pg = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    assert "timezone('UTC', document_chunks.published_at) AS published_at" in pg
    assert "timezone('UTC', document_chunks.recorded_at) AS recorded_at" in pg
    lite = " ".join(str(statement.compile(dialect=sqlite.dialect())).split())
    assert "timezone" not in lite and "document_chunks.published_at" in lite


def test_chunk_timestamp_predicates_and_ddl_keep_the_bare_timestamptz_column():
    where = " ".join(str(select(DocumentChunk.id).where(DocumentChunk.published_at <= T0).compile(
        dialect=postgresql.dialect())).split())
    assert "timezone" not in where  # the cutoff predicate and its index use the stored column
    ddl = str(CreateTable(DocumentChunk.__table__).compile(dialect=postgresql.dialect()))
    assert "published_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl and "recorded_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl


def test_the_raw_search_sql_selects_the_utc_wall_clock_and_filters_on_the_stored_column():
    for statement in (SEARCH_SQL, NEAREST_SQL):
        sql = " ".join(str(statement).split())
        assert sql.count("timezone('UTC', published_at) AS published_at") == 1
        assert sql.index("timezone('UTC', published_at)") < sql.index("FROM document_chunks")
    assert "timezone" not in " ".join(str(SEARCH_SQL).split()).split("WHERE")[1].split("ORDER BY")[0]


def test_the_shared_utc_datetime_is_unchanged():
    assert UTCDateTime.column_expression is TypeDecorator.column_expression
    assert "timezone(" not in str(select(Trade.trade_timestamp).compile(dialect=postgresql.dialect()))
