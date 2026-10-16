"""Feature 009 step 3: migration 0003 (document_chunks). New tests only; tests/test_migration.py is unmodified.

Offline rendering cannot see a database, so it proves DDL only, never that the `vector` extension exists. The live
upgrade/downgrade and the missing-extension failure are plan step 6 (the latter stays BLOCKED until a separate disposable
PostgreSQL database without the extension is provisioned).
"""
import argparse
import importlib.util
import io

import pytest
from alembic import command
from sqlalchemy import Integer, create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.domain import limits
from app.domain.retrieval import EMBEDDING_DIMENSION, VectorExtensionMissingError
from app.models.chunk import DocumentChunk
from tests.test_migration import BACKEND, PG_URL, alembic_config


def _offline(*args) -> str:
    cfg = alembic_config()
    cfg.cmd_opts = argparse.Namespace(x=[f"url={PG_URL}"])
    cfg.output_buffer = io.StringIO()
    args[0](cfg, *args[1:], sql=True)
    return cfg.output_buffer.getvalue()


def _revision_0003():
    spec = importlib.util.spec_from_file_location("rev_0003", BACKEND / "migrations" / "versions" / "0003_document_chunks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_render_of_document_chunks_ddl_only():
    """Rendering only: the SQL below says nothing about whether a real database has the extension."""
    sql = _offline(command.upgrade, "head")
    assert "CREATE TABLE document_chunks" in sql
    assert "embedding vector(768) NOT NULL" in sql
    assert "CONSTRAINT uq_document_chunks_user_source_chunk UNIQUE (user_id, source_id, chunk_index)" in sql
    assert "CREATE INDEX ix_document_chunks_user_published ON document_chunks (user_id, published_at)" in sql
    assert "published_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql and "chunk_index INTEGER NOT NULL" in sql
    assert "CREATE EXTENSION" not in sql.upper() and "DROP EXTENSION" not in sql.upper()
    assert "pg_extension" not in sql  # the runtime extension check is skipped offline, never rendered as a claim
    assert " FLOAT" not in sql.upper() and "DOUBLE" not in sql.upper()
    assert "USING hnsw" not in sql and "ivfflat" not in sql  # exact scan, no vector index


def test_offline_downgrade_drops_only_the_feature_009_objects():
    sql = _offline(command.downgrade, "0003:0002")
    assert "DROP INDEX ix_document_chunks_user_published" in sql and "DROP TABLE document_chunks" in sql
    assert "EXTENSION" not in sql.upper() and "trades" not in sql and "import_batches" not in sql


def test_frozen_migration_constants_agree_with_the_model_and_limits():
    rev = _revision_0003()
    assert rev.DIMENSION == EMBEDDING_DIMENSION == 768
    assert rev.SOURCE_ID_LENGTH == limits.MAX_SOURCE_ID_LENGTH == DocumentChunk.__table__.c.source_id.type.length
    assert rev.EMBEDDING_MODEL_LENGTH == limits.MAX_EMBEDDING_MODEL_LENGTH
    assert (rev.revision, rev.down_revision) == ("0003", "0002")


def test_chunk_index_is_an_integer_column_matching_max_chunk_index():
    """PostgreSQL INTEGER is int4: MAX_CHUNK_INDEX must be its maximum, and the column must not be BIGINT."""
    column_type = DocumentChunk.__table__.c.chunk_index.type
    assert type(column_type) is Integer
    assert limits.MAX_CHUNK_INDEX == 2**31 - 1
    assert "chunk_index INTEGER NOT NULL" in _offline(command.upgrade, "head")


def test_sqlite_upgrade_creates_the_test_only_text_stand_in_and_downgrade_removes_only_it():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")  # no extension is required on SQLite
        columns = {c["name"]: c for c in inspect(conn).get_columns("document_chunks")}
        assert str(columns["embedding"]["type"]) == "TEXT"  # test-only stand-in; no vector semantics on SQLite
        assert all(not c["nullable"] for c in columns.values())
        assert {u["name"] for u in inspect(conn).get_unique_constraints("document_chunks")} == {
            "uq_document_chunks_user_source_chunk"}
        command.downgrade(cfg, "0002")
        tables = set(inspect(conn).get_table_names())
        assert "document_chunks" not in tables and {"users", "trades", "import_batches"} <= tables


def test_the_missing_extension_error_is_specific_and_identifiable():
    err = VectorExtensionMissingError()
    assert str(err).startswith("VECTOR_EXTENSION_MISSING")
    with pytest.raises(VectorExtensionMissingError):
        raise err
