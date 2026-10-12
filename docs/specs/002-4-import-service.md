# Spec 002-4: Tradebook import service

Status: delivered (Step 5), service only: no route, schemas or API mapping yet. Plan: `002-zerodha-tradebook-import.md`,
`002a-decisions.md` (OPEN-6, 7, 10, 11), `002b-schema-api-tests.md`. Code: `backend/app/services/tradebook_import.py`. Tests:
`tests/test_tradebook_import.py` plus additions in `test_holdings`, `test_trade_repository`, `test_ledger_service`,
`test_import_boundaries`, `test_postgres_integration` (live only).

## Interface
`TradebookImportService.for_session(session, clock=, id_factory=).import_tradebook(user_id=, file_name=, content=) -> ImportResult`.
`ImportResult(import_batch_id, file_name, file_sha256, total_rows, imported, duplicates, rejected_total, rejected, quarantined_isins,
fees_taxes_provided=False)`. `rejected` holds the first 200 `RowRejection(line, code, message)` in ascending file line;
`rejected_total` is always exact. Row outcomes are results, never exceptions. Raised: `InvalidImportFileError` (file level),
`LedgerBusyError` (lock held), `RuntimeError` (missing `users` row or a counter mismatch, both setup/bug errors).

## Flow
1. SHA-256 of the bytes, then `parse_tradebook` with no database access. A file-level failure raises; nothing is written.
2. `LedgerService.lock_user`: `SELECT ... FOR UPDATE NOWAIT` on the user's `users` row. Held lock -> `LedgerBusyError` before any write.
3. Create the `import_batches` row (counts 0).
4. Pass 1, file order: a key `(exchange, trade_id)` seen earlier in the file is compared with its FIRST occurrence; otherwise
   `original_by_key` looks up the ledger. Identical comparable fields -> `duplicate` (counted); any difference ->
   `conflicting_duplicate` (rejected). Comparable: isin, symbol, side, quantity, price (numeric), UTC timestamp, order_id; an
   existing NULL isin/order_id never conflicts. Corrected or voided originals stay the target. Neither outcome is stored or
   evaluated for oversell.
5. Pass 2, canonical order `(timestamp, BUY before SELL, int(trade_id), line)` over the genuinely new rows: an ISIN already
   quarantined -> `after_oversell`; else fold the ISIN's effective rows plus the candidate with `find_oversell(group_key=ISIN)`.
   Oversell -> `oversell` and the ISIN is quarantined for the rest of this import (other ISINs continue). A running total at the
   calculation limit -> `numeric_limit_exceeded` (no quarantine). Otherwise insert in a savepoint with `recorded_at` from the clock.
   A lost unique-index race is re-classified against the winning row.
6. Update the batch counters, check `imported + duplicates + rejected_total == total_rows`, commit. Any exception rolls back the
   whole upload, including the batch.

## Stored trade
`source=IMPORT`, `status=EXECUTED`, `currency=INR`, `broker=ZERODHA`, `import_batch_id`, ISIN/symbol/exchange/side/quantity/price/UTC
timestamp/`trade_id`/`order_id` from the row, fees and taxes 0, `charges_provided=false`, name/asset_type/market_session NULL.
Cost basis is understated and realized P&L overstated until corrected.

## Supporting changes
- `holdings.py`: keyword-only `group_key` on `find_oversell`/`_fold`; the default groups by listing (Step 6 changed the default to the holding key; the override is kept).
- Ledger consistency: `TradeInput.isin` (exactly 12 ASCII `[A-Z0-9]`, never normalized; required by `record`). `record` and `correct` store
  `charges_provided=true`; `correct` takes a `CorrectionInput` that always carries an explicit ISIN (Step 5 let it inherit the
  target's; superseded in Step 6); `void` copies `isin` and
  `charges_provided` (H-4). Corrections and voids are MANUAL with no batch, so `source=IMPORT iff import_batch_id` holds.
  `_check_no_oversell` now groups by `HoldingKey` (ISIN, else legacy listing) for the candidate and the replaced row, so voiding or
  shrinking an NSE buy that covers a BSE sell of the same ISIN is refused. (Step 6: `holdings()` groups by the same key.)
- A calculation-limit rejection (`numeric_limit_exceeded`) never quarantines an ISIN; only `oversell` does.
- `LedgerService.lock_user` is taken first in `record`, `correct`, `void` and the import. `TradeRepository.lock_user_ledger` and
  `list_effective_for_isins` back it; `LedgerBusyError` has code `ledger_busy`.

## Verification
Full suite 657 passed, 54 skipped on Python 3.14.5 and on 3.12; `pip check` clean. The 54 skips are live-PostgreSQL tests (4 new:
real NOWAIT refusal, import vs manual write both ways with no partial batch, end-to-end import, rollback). Those and the lock
semantics are UNVERIFIED: no PostgreSQL server was available. SQLite tests prove service behavior only. The PostgreSQL statement
text (`FOR UPDATE NOWAIT`) is asserted offline.

## Known limits and next steps
- The route, schemas, 409 mapping, nullable `TradeOut` fields, ISIN-grouped holdings and the required ISIN on manual create/correct
  were built in Step 6 (`002-5-api-and-holdings.md`). Step 5 originally let `correct()` inherit an omitted ISIN; Step 6 replaced that with `CorrectionInput`.
- Explicit fees on a correction of a `charges_provided=false` target (3a) need `TradeCorrectionIn` (omitted vs explicit 0) and land
  with the schema step. Until then a correction stores `charges_provided=true` with the fees it was given (default 0).
- The HTTP manual API still sends no ISIN; making it required is the schema step. A legacy NULL-ISIN correction stays NULL.
- The parser stays the import's only row validator; DB CHECKs are the last guard.
- A repeat of a key whose first occurrence was rejected is classified against that first occurrence and not evaluated again.
- The per-ISIN fold is O(rows of that ISIN) per row; the 5,000-row cap is a safety limit, not a performance guarantee.
