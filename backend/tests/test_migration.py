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
    assert "CREATE UNIQUE INDEX uq_trades_dedupe ON trades (user_id, broker, exchange, broker_trade_id)" in sql
    assert "DROP INDEX uq_trades_dedupe" in sql  # 0002 replaces the 0001 key
    assert "WHERE broker_trade_id IS NOT NULL AND supersedes_trade_id IS NULL" in sql
    assert "CREATE TABLE import_batches" in sql and "UNIQUE (user_id, id)" in sql
    assert "FOREIGN KEY(user_id, import_batch_id) REFERENCES import_batches (user_id, id)" in sql
    assert "ALTER TABLE trades ALTER COLUMN name DROP NOT NULL" in sql
    assert "ALTER TABLE trades ADD COLUMN charges_provided BOOLEAN DEFAULT true NOT NULL" in sql
    assert "(source = 'IMPORT') = (import_batch_id IS NOT NULL)" in sql
    assert "isin IS NULL OR length(isin) = 12" in sql
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
        assert {u["name"] for u in insp.get_unique_constraints("import_batches")} == {"uq_import_batches_user_id_id"}
        fks = {fk["name"]: fk for fk in insp.get_foreign_keys("trades")}
        assert fks["fk_trades_import_batch_same_user"]["constrained_columns"] == ["user_id", "import_batch_id"]
        assert fks["fk_trades_import_batch_same_user"]["referred_table"] == "import_batches"
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


def _engine():
    return create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def test_0002_upgrade_preserves_manual_rows_and_downgrade_restores_the_old_shape():
    engine = _engine()
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
        conn.execute(text("INSERT INTO users (id, created_at) VALUES ('0000000000000000000000000000000a', '2026-01-01')"))
        conn.execute(text(
            "INSERT INTO trades (id, user_id, symbol, name, asset_type, exchange, currency, side, quantity,"
            " price_per_unit, brokerage_fee, taxes, trade_timestamp, recorded_at, broker, broker_trade_id, source,"
            " market_session, status) VALUES ('00000000000000000000000000000001', '0000000000000000000000000000000a',"
            " 'X', 'X', 'STOCK', 'NSE', 'INR', 'BUY', 1, 1, 0, 0, '2026-01-01', '2026-01-01', 'zerodha', 'T1', 'MANUAL',"
            " 'REGULAR', 'EXECUTED')"
        ))
        command.upgrade(cfg, "0002")
        row = conn.execute(text("SELECT isin, charges_provided, import_batch_id, name FROM trades")).one()
        assert row.isin is None and row.charges_provided in (1, True) and row.import_batch_id is None and row.name == "X"
        command.downgrade(cfg, "0001")
        insp = inspect(conn)
        assert "import_batches" not in insp.get_table_names()
        assert {c["name"] for c in insp.get_columns("trades")} == {
            c["name"] for c in insp.get_columns("trades") if c["name"] not in {"isin", "charges_provided", "import_batch_id"}
        }
        index = {i["name"]: i for i in insp.get_indexes("trades")}["uq_trades_dedupe"]
        assert index["column_names"] == ["user_id", "broker", "broker_trade_id"]
        assert conn.execute(text("SELECT count(*) FROM trades")).scalar() == 1


def test_0002_downgrade_fails_loudly_instead_of_rewriting_rows_with_null_fields():
    engine = _engine()
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0002")
        conn.execute(text("INSERT INTO users (id, created_at) VALUES ('0000000000000000000000000000000a', '2026-01-01')"))
        conn.execute(text(
            "INSERT INTO trades (id, user_id, symbol, name, asset_type, exchange, currency, side, quantity,"
            " price_per_unit, brokerage_fee, taxes, trade_timestamp, recorded_at, source, market_session, status)"
            " VALUES ('00000000000000000000000000000001', '0000000000000000000000000000000a', 'X', NULL, NULL, 'NSE',"
            " 'INR', 'BUY', 1, 1, 0, 0, '2026-01-01', '2026-01-01', 'MANUAL', NULL, 'EXECUTED')"
        ))
        with pytest.raises(Exception):
            command.downgrade(cfg, "0001")
