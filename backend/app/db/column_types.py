"""Portable column types: exact Decimal and aware-UTC datetimes on PostgreSQL and SQLite.

`UTCDateTime` and the Feature 009 `Vector` live in `app.db.portable_types` (they need no money module) and are re-exported.
"""
from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.types import TypeDecorator

from app.db.portable_types import UTCDateTime, Vector  # noqa: F401  (re-exported)
from app.domain.numeric import SCALE

PRECISION = 20


class ExactDecimal(TypeDecorator):
    """NUMERIC(20, 6) on PostgreSQL; exact decimal text on SQLite (never a float)."""

    impl = Numeric(PRECISION, SCALE, asdecimal=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(40))
        return dialect.type_descriptor(Numeric(PRECISION, SCALE, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError("money and quantity columns accept Decimal only")
        if dialect.name == "sqlite":
            return format(value, "f")
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)

