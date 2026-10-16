"""Portable column types that need no money module.

The Feature 009 retrieval model may not reach `app.domain.numeric`, even transitively (tests/test_import_boundaries.py), so
these types live apart from `ExactDecimal`. `app.db.column_types` re-exports them; existing imports are unchanged.
"""
from datetime import timezone

from sqlalchemy import DateTime, Text, cast
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import TypeDecorator, UserDefinedType


class UTCDateTime(TypeDecorator):
    """Timestamp stored as UTC; naive values are refused; results are always aware UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive timestamps are not accepted")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class _UTCWallClock(FunctionElement):
    """`timezone('UTC', col)` on PostgreSQL: the UTC wall clock as a naive timestamp; the bare column elsewhere."""

    inherit_cache = True
    type = UTCDateTime()
    name = "timezone"


@compiles(_UTCWallClock)
def _utc_wall_clock_default(element, compiler, **kw):
    return compiler.process(element.clauses.clauses[0], **kw)


@compiles(_UTCWallClock, "postgresql")
def _utc_wall_clock_postgresql(element, compiler, **kw):
    return f"timezone('UTC', {compiler.process(element.clauses.clauses[0], **kw)})"


class ChunkUTCDateTime(UTCDateTime):
    """`UTCDateTime` for Feature 009 chunk columns whose instants may sit at year 1 or year 9999.

    psycopg decodes `timestamptz` in the session time zone, so an edge instant can fall outside Python's year range
    (`0001-01-01Z` in America/Los_Angeles, `9999-12-31T23:59:59.999999Z` in Asia/Kolkata). Selecting the UTC wall clock avoids
    that without touching session state; `process_result_value` already reads a naive value as UTC. Storage and DDL are unchanged.
    """

    cache_ok = True

    def column_expression(self, col):
        return _UTCWallClock(col)


class _PgVector(UserDefinedType):
    """pgvector's `vector(D)`. Values are bound as text and cast server-side, so PostgreSQL also checks the dimension."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dimension})"

    def bind_expression(self, bindvalue):
        return cast(bindvalue, self)


class Vector(TypeDecorator):
    """`vector(D)` on PostgreSQL (authoritative); TEXT on SQLite, a test-only stand-in with no vector semantics.

    Accepts only pre-encoded `[v1,...]` text (see `repositories/chunks.py`), bound as `CAST(:p AS vector(D))` on PostgreSQL.
    The column is write-only: it is never read back, so reading it raises.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimension: int) -> None:
        super().__init__()
        self.dimension = dimension

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector(self.dimension))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str) or not (value.startswith("[") and value.endswith("]")):
            raise TypeError("vector columns accept pre-encoded '[v1,...]' text only")
        return value

    def process_result_value(self, value, dialect):
        raise TypeError("vector columns are write-only and are never read back")
