"""Limits for bounded trade fields. Single source for validation, ORM columns and the migration test."""
from datetime import datetime, timezone

MAX_SYMBOL_LENGTH = 64
MAX_NAME_LENGTH = 256
MAX_BROKER_LENGTH = 64
MAX_BROKER_TRADE_ID_LENGTH = 128
MAX_ORDER_ID_LENGTH = 128
MAX_NOTES_LENGTH = 2000

# Supported trade_timestamp window (as a UTC instant). It stays one day inside the calendar's first and last instants so
# that converting to or from any session/offset timezone remains representable: PostgreSQL returns timestamptz in the
# session timezone, and the instants 0001-01-01T00:00Z and 9999-12-31T23:59:59Z fail to read back in some zones.
MIN_TRADE_TIMESTAMP = datetime(1, 1, 2, tzinfo=timezone.utc)
MAX_TRADE_TIMESTAMP = datetime(9999, 12, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)
