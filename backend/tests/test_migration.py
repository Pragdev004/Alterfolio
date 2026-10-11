import argparse
import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.models.base import Base

BACKEND = Path(__file__).resolve().parent.parent
PG_URL = "postgresql+psycopg://user:pass@localhost/alterfolio"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def test_offline_postgres_sql_renders_the_intended_ddl():
    cfg = alembic_config()
    cfg.cmd_opts = argparse.Namespace(x=[f"url={PG_URL}"])
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    sql = cfg.output_buffer.getvalue()
    assert "NUMERIC(20, 6)" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE UNIQUE INDEX uq_trades_dedupe ON trades (user_id, broker, broker_trade_id)" in sql
    assert "WHERE broker_trade_id IS NOT NULL AND supersedes_trade_id IS NULL" in sql
    assert "FOREIGN KEY(user_id, supersedes_trade_id) REFERENCES trades (user_id, id)" in sql
    assert "CONSTRAINT uq_trades_supersedes_trade_id UNIQUE (supersedes_trade_id)" in sql
    assert " FLOAT" not in sql.upper() and "DOUBLE" not in sql.upper()


def test_migration_matches_the_models_and_downgrades_cleanly():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        insp = inspect(conn)
        assert set(insp.get_table_names()) - {"alembic_version"} == set(Base.metadata.tables)
        for name, table in Base.metadata.tables.items():
            assert {c["name"] for c in insp.get_columns(name)} == {c.name for c in table.columns}
            assert {i["name"] for i in insp.get_indexes(name)} == {i.name for i in table.indexes}
            model_checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
            assert {c["name"] for c in insp.get_check_constraints(name)} == model_checks
        uniques = {u["name"] for u in insp.get_unique_constraints("trades")}
        assert uniques == {"uq_trades_user_id_id", "uq_trades_supersedes_trade_id"}
        command.downgrade(cfg, "base")
        assert set(inspect(conn).get_table_names()) <= {"alembic_version"}


LIVE_URL = os.environ.get("ALTERFOLIO_TEST_DATABASE_URL")
live_only = pytest.mark.skipif(not LIVE_URL, reason="no live PostgreSQL configured (ALTERFOLIO_TEST_DATABASE_URL)")


def require_empty_database(conn) -> None:
    """Safety: live tests migrate up and down, so they must only ever run on an empty throwaway database."""
    tables = set(inspect(conn).get_table_names())
    existing = tables & {"users", "trades"}
    if "alembic_version" in tables and conn.execute(text("SELECT count(*) FROM alembic_version")).scalar():
        existing.add("alembic_version (with a revision)")  # an empty table is just what a downgrade leaves behind
    if existing:
        pytest.fail(f"refusing to run: target database already has {sorted(existing)}; use an empty throwaway database")


@live_only
def test_live_postgres_upgrade_and_downgrade():
    engine = create_engine(LIVE_URL)
    cfg = alembic_config()
    try:
        with engine.begin() as conn:
            require_empty_database(conn)
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            assert {"users", "trades"} <= set(inspect(conn).get_table_names())
            command.downgrade(cfg, "base")
            assert not ({"users", "trades"} & set(inspect(conn).get_table_names()))
    finally:
        engine.dispose()


def test_migrated_text_columns_match_the_declared_limits():
    from app.domain import limits

    expected = {
        "symbol": limits.MAX_SYMBOL_LENGTH, "name": limits.MAX_NAME_LENGTH, "broker": limits.MAX_BROKER_LENGTH,
        "broker_trade_id": limits.MAX_BROKER_TRADE_ID_LENGTH, "order_id": limits.MAX_ORDER_ID_LENGTH,
        "notes": limits.MAX_NOTES_LENGTH,
    }
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        migrated = {c["name"]: c["type"].length for c in inspect(conn).get_columns("trades") if c["name"] in expected}
    model = {name: Base.metadata.tables["trades"].c[name].type.length for name in expected}
    assert migrated == expected and model == expected
