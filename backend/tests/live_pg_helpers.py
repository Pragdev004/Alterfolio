"""Safety guards shared by the Feature 009 live PostgreSQL tests (spec section 6). Tests never create or drop `vector`."""
import pytest
from sqlalchemy import inspect, text

# Never used for destructive tests (owner, 2026-10-15).
FORBIDDEN_DATABASES = frozenset({"academic_os", "intrinsic_db"})
PROJECT_TEST_DATABASE = "alterfolio_test"


def database_name(conn) -> str:
    return conn.execute(text("SELECT current_database()")).scalar_one()


def require_safe_target(conn) -> str:
    name = database_name(conn)
    if name in FORBIDDEN_DATABASES:
        pytest.fail(f"refusing to run destructive tests against {name}")
    return name


def vector_installed(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first() is not None


def require_vector(conn) -> None:
    if not vector_installed(conn):
        pytest.fail("the `vector` extension is not installed here; tests never create it (ask the owner)")


def tables(conn) -> set[str]:
    return set(inspect(conn).get_table_names())


def embedding_column_type(conn) -> str:
    return conn.execute(text(
        "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
        "WHERE a.attrelid = 'document_chunks'::regclass AND a.attname = 'embedding'"
    )).scalar_one()
