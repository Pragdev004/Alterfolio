"""Portable column types: exact Decimal and aware-UTC datetimes on PostgreSQL and SQLite."""
from datetime import timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.types import TypeDecorator

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

