# Spec 002-3: Import persistence foundation

Status: delivered and approved (Step 4). No behavior change to the ledger, holdings or API. Plan: `002b-schema-api-tests.md`
("Schema: migration 0002"), decisions in `002a-decisions.md` (OPEN-1, 1b, OPEN-2, OPEN-3, OPEN-4, OPEN-10).

## Purpose
Add the storage and identity primitives Feature 002 needs, so the later ledger and import-service steps have a schema to
write to.

## Migration `0002` (revision 0002, down 0001; nothing backfilled)
- Creates `import_batches(id, user_id, file_name, file_sha256, total_rows, imported, duplicates, rejected_total, created_at)`
  with `UNIQUE(user_id, id)` and an index on `user_id`. `file_sha256` is not unique, so the same file can be uploaded twice.
- `trades` gains `isin` (12 chars, NULL), `charges_provided` (NOT NULL, server default true) and `import_batch_id` (NULL).
  `name`, `asset_type` and `market_session` become nullable.
- Composite FK `fk_trades_import_batch_same_user` on `(user_id, import_batch_id)` to `import_batches(user_id, id)`.
- CHECKs: `isin_length` (`isin IS NULL OR length(isin) = 12`) and `import_source_has_batch` (`source = 'IMPORT'` exactly when
  `import_batch_id IS NOT NULL`). Manual, correction and void rows are MANUAL with no batch.
- `uq_trades_dedupe` is rebuilt on `(user_id, broker, exchange, broker_trade_id)` with the same partial predicate (original
  rows with a broker trade id). The same id on NSE and BSE are two trades.
- Downgrade restores the old shape and index. Restoring NOT NULL fails loudly if NULL rows exist; data is never rewritten.
- Dialects: plain ALTERs on PostgreSQL, table rebuild through `batch_alter_table` on SQLite (tests only).

## Models and repositories
- `Trade` has the new columns and constraints; `charges_provided` defaults true in Python and SQL (imports will set false).
  The append-only guard is unchanged.
- `ImportBatch` model. `ImportBatchRepository`: `add` (counts start at 0), user-scoped `get`, and `update_counts` (changes only the
  four counters; an unknown or another user's batch raises `LookupError`). There is no delete. It does not check that
  `imported + duplicates + rejected_total == total_rows`; the import service owns that.
- `TradeRepository.original_by_key(user_id, broker, exchange, broker_trade_id)` replaces `original_by_broker_trade_id`.
  The only call site, `LedgerService._refuse_duplicate`, now passes the exchange. No other ledger change.
- `HoldingKey` (`app/domain/holding_key.py`, stdlib only): an ISIN key ignores symbol and exchange; a legacy key is
  `(symbol, exchange)` and never equals an ISIN key; sort order is ISIN ascending, then legacy by symbol and exchange.
  It is not used by the fold, `list_effective` or any API yet.
- New limits in `domain/limits.py`: `ISIN_LENGTH = 12`, `MAX_FILE_SHA256_LENGTH = 64`.

## Verification
- Tests: `test_holding_key`, `test_import_batch_repository`, `test_trade_repository`, `test_migration`,
  `test_import_boundaries`, `test_repo_hygiene`, plus updates to `test_ledger_service`, `conftest.py` (`make_batch`).
- Results: Step 4 files 85 passed, 1 skipped. Full suite 568 passed, 50 skipped on Python 3.14.5 and on 3.12; `pip check` clean.
- Unverified: the 50 skips are live-PostgreSQL tests (no `ALTERFOLIO_TEST_DATABASE_URL` or server was available). The PostgreSQL
  DDL text is asserted offline but never executed. This is an outstanding verification item, not a known failure.

## Known limits
Upgrading a database that holds a `source = IMPORT` row without a batch would fail the new CHECK. Feature 001 never writes
such rows, so no test pins this. Still pending: ISIN keyed fold and oversell check, user lock, `import` entry point, `void`
and `correct` copying `isin` and `charges_provided`, import service, route, schemas, holdings shape.
