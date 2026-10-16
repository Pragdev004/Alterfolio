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

# Tradebook import (plan 002a OPEN-8). The row cap is an implementation safety limit, not a performance guarantee.
MAX_IMPORT_FILE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
MAX_IMPORT_FILE_NAME_LENGTH = 255
MAX_LISTED_REJECTIONS = 200
ISIN_LENGTH = 12
MAX_FILE_SHA256_LENGTH = 64

# Feature 009 retrieval (docs/specs/009-rag-date-cutoff.md section 4). The text cap is an owner-confirmed product limit on the
# caller's original chunk or query text in Python characters, counted before the embedding role prefix; it is not a guarantee
# that the embedding model accepts the text (its context limit is enforced separately, spec section 7).
MAX_CHUNK_TEXT_LENGTH = 4000
MAX_SOURCE_ID_LENGTH = 256
MAX_CHUNK_INDEX = 2**31 - 1  # fits a PostgreSQL INTEGER column
MIN_SEARCH_K = 1
MAX_SEARCH_K = 50
MAX_EMBEDDING_MODEL_LENGTH = 128
