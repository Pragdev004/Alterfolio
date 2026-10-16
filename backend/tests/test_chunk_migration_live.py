"""Feature 009 step 6: the document_chunks migration on live PostgreSQL (spec sections 6 and 9).

Both tests migrate up and down, so they run only on an EMPTY throwaway database. The extension is never created or dropped.
"""
import os

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.domain.retrieval import VectorExtensionMissingError
from tests.live_pg_helpers import (
    FORBIDDEN_DATABASES,
    PROJECT_TEST_DATABASE,
    embedding_column_type,
    require_safe_target,
    require_vector,
    tables,
    vector_installed,
)
from tests.test_migration import LIVE_URL, alembic_config, live_only, require_empty_database

NOVECTOR_URL = os.environ.get("ALTERFOLIO_TEST_NOVECTOR_DATABASE_URL")


@live_only
def test_upgrade_creates_document_chunks_and_downgrade_removes_it_keeping_the_extension():
    engine = create_engine(LIVE_URL)
    cfg = alembic_config()
    try:
        with engine.begin() as conn:
            require_safe_target(conn)
            require_empty_database(conn)
            require_vector(conn)
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            assert "document_chunks" in tables(conn)
            assert embedding_column_type(conn) == "vector(768)"
            command.downgrade(cfg, "0002")
            assert "document_chunks" not in tables(conn) and {"users", "trades"} <= tables(conn)
            assert vector_installed(conn)
            command.downgrade(cfg, "base")
        with engine.connect() as conn:  # after commit, in a fresh transaction
            assert vector_installed(conn)
            assert not ({"document_chunks", "users", "trades"} & tables(conn))
    finally:
        engine.dispose()


@pytest.mark.skipif(not NOVECTOR_URL, reason=(
    "BLOCKED: the separate disposable PostgreSQL database without `vector` is not provisioned "
    "(ALTERFOLIO_TEST_NOVECTOR_DATABASE_URL); this skip is not verification"))
def test_upgrade_without_the_extension_fails_with_vector_extension_missing_and_creates_nothing():
    engine = create_engine(NOVECTOR_URL)
    cfg = alembic_config()
    with engine.connect() as conn:  # every guard runs before anything is migrated (and before any cleanup could run)
        name = require_safe_target(conn)
        if name in FORBIDDEN_DATABASES | {PROJECT_TEST_DATABASE}:
            engine.dispose()
            pytest.fail(f"the missing-extension test must not run against {name}")
        if vector_installed(conn):
            engine.dispose()
            pytest.fail(f"{name} has `vector` installed; this test needs a database without it (never drop it)")
        require_empty_database(conn)
    try:
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0002")
        with pytest.raises(VectorExtensionMissingError) as info:
            with engine.begin() as conn:
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
        assert str(info.value).startswith("VECTOR_EXTENSION_MISSING")
        with engine.connect() as conn:
            assert "document_chunks" not in tables(conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002"
            assert not vector_installed(conn)
    finally:
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
        engine.dispose()
