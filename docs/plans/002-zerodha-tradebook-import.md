# Feature 002: Zerodha tradebook import

Status: IMPLEMENTED and verified (SQLite offline suite; PostgreSQL 16.14 live suite; Python 3.14.5 and 3.12). Plan rev 4 (2026-10-11)
below is kept as approved; the as-built descriptions are in `docs/specs/002-*.md`, which win where they differ.
Files: this one (scope, format, mapping, flow, API), `002a-decisions.md` (owner decisions: OPEN-#, 1a-1d, 3a, A-4, H-4),
`002b-schema-api-tests.md` (migration, 001 contract changes, semantics, tests, doc checklist). Sources: `docs/design.md`,
`docs/spec.md`, `docs/v1-lineage.md`, plan 001. Privacy: the real exports stay outside the repo; plans hold structure only,
never symbols, ids, prices or dates.

## Scope
In: parse a Zerodha Console equity tradebook CSV; per-row validation; `source=IMPORT` trades for the current user; idempotent
re-import; `import_batches`; `POST /imports/tradebook`; counts and per-row rejection reasons; the Feature 001 changes forced by
ISIN identity (002a/002b). Out: contract notes, P&L reports, other books/brokers, corporate actions, quotes (003), UI, dry-run,
rejected-row persistence, background jobs, opening-balance feature.

## Already decided by the project (not re-opened)
- D1 Dedupe key per OPEN-2 (includes exchange); never `order_id`. D2 Rows pass the 001 validation rules (Decimal, <= 6 dp,
  > 0, window, text limits, `MAX_AMOUNT`); no repair or rounding. D3 Long-only: oversell via the 001 D12 candidate-set fold;
  BUY before SELL at equal timestamps. D4 User scope via `get_current_user_id`; every query carries `user_id`.
- D5 A bad row is rejected with a reason, other rows import (FR-5). D6 Pure parser in `services/` (stdlib `csv`; no
  sqlalchemy/fastapi/pydantic/clock). D7 Business errors are 422 `{"detail": {"code","message"}}`.

## Real format (observed in 2 files, 30 rows total)
Header, identical in both, 13 columns, all text: `symbol,isin,trade_date,exchange,segment,series,trade_type,auction,
quantity,price,trade_id,order_id,order_execution_time`. UTF-8, no BOM, LF, no quoting needed.
| Column | Observed | Unobserved / risk |
| --- | --- | --- |
| symbol | letters only | punctuation, BSE numeric codes |
| isin | 12 chars `AAA999A99999`; empty on 1 of 30 rows | other empties |
| trade_date | `YYYY-MM-DD`, equals the date in `order_execution_time` | none |
| exchange / segment | `NSE`,`BSE` / always `EQ` | others |
| series / trade_type / auction | NSE `EQ`, BSE `A` / lowercase buy,sell / always `false` | other groups / `true` |
| quantity, price | exactly 6 dp, quantities integral (like `333.799988`) | fractions; more than 6 dp |
| trade_id | digits, 6-9 chars, unique across both files | repeats across days/exchanges |
| order_id | digits; 16 (NSE) or 19 (BSE); unique per row | partial fills share it (spec), none seen |
| order_execution_time | `YYYY-MM-DDTHH:MM:SS`, no zone, 09:00:02-14:53:04 | other formats |
Aggregate facts: no overlapping `(exchange, trade_id)` between files (overlap/conflict behaviour unobserved); five companies
trade on both NSE and BSE (same ISIN); the second file has sells with no earlier buy in the imported history. Conflicts with
design/001 found here (identity, absent name/type/session, absent fees, dedupe key lacking exchange, partial history) are
resolved in 002a.

## Field mapping
| Trade field | From file | Rule |
| --- | --- | --- |
| symbol | `symbol` | verbatim, trimmed, non-empty (canonicalization stays FR-9/003) |
| exchange, side | `exchange`, `trade_type` | `NSE`/`BSE`; `buy`/`sell` (case-folded); else `unsupported_exchange`/`invalid_side` |
| quantity, price_per_unit | `quantity`, `price` | `Decimal(text)` verbatim, never float or normalized; 7+ dp, exponent, sign rejected |
| trade_timestamp | `order_execution_time` | fixed IST -> UTC, strict format; `trade_date` must match (OPEN-5) |
| isin | `isin` | `[A-Z0-9]{12}`; empty -> `missing_isin` |
| broker, broker_trade_id, order_id | constant `ZERODHA`, `trade_id` (raw digits), `order_id` | order_id stored only |
| source/status/currency/recorded_at | server | `IMPORT` / `EXECUTED` / `INR` / injected clock per row |
| name, asset_type, market_session | none | NULL (OPEN-3) |
| brokerage_fee, taxes, charges_provided | none | 0, 0, false (OPEN-4) |
| import_batch_id | server | the batch of this upload |
| segment, series, auction | same | `EQ`; `EQ` on NSE / `A` on BSE; `false`; else `unsupported_*` (never dropped) |
Normative row-code table and the per-row pipeline order are in `002b`. Messages name the field and quote at most a short
sanitized excerpt of the value.

## Processing flow and transactions
1. Stream the request under the 2 MB cap (A-4), SHA-256 of raw bytes, decode, check header and row cap. File-level failure
   -> 422 `invalid_import_file`; no batch, no trades.
2. Parse each row to a value object or `RowRejection(line, code, message)`; within-file duplicates per OPEN-6.
3. Take the user lock (OPEN-11); a held lock returns 409 before anything is written.
4. One transaction: insert `import_batches`, then rows in canonical order `(timestamp, BUY first, int(trade_id))`; per row
   classify (duplicate/conflict, quarantine, oversell) and insert through a `source=IMPORT` entry point on `LedgerService`
   (same oversell and duplicate checks as `_append`, savepointed insert via `TradeRepository.add`). Update batch counts; commit once.
5. Unexpected exceptions (database error, bug) roll back everything including the batch and return 500. Row rejections never
   abort the file. A lost unique-index race is re-classified by comparing the winner (never assumed duplicate).

## API
`POST /imports/tradebook` (multipart, one part `file`) -> 201 `{import_batch_id, file_name, file_sha256, total_rows, imported,
duplicates, rejected_total, rejected:[first 200 {row, code, message}], quarantined_isins, fees_taxes_provided}`. Invariant:
`imported + duplicates + rejected_total == total_rows`. Errors: 422 `invalid_import_file`, 422 validation, 409 `ledger_busy`,
500 on rollback. 001 route changes are in `002b`.

## Behavior
- Re-import yields zero new rows (all `duplicate`); two files in sequence give the union; overlapping files add only unseen
  keys; file order does not matter. An imported row later corrected or voided: re-import is still `duplicate`.
- Another user's identical file is independent. Partial fills (same `order_id`, different `trade_id`) import separately.

## Order
1 Owner approves this plan. 2 Update design/spec/CLAUDE.md/plan-001 wording (checklist in 002b). 3 Streaming-upload spike
test, boundary test edges, synthetic fixture, hygiene test. 4 Pure parser. 5 Migration, models, repository, domain `HoldingKey`.
6 Ledger changes (ISIN identity, lock, import entry point, correction rules). 7 Import service and transaction tests.
8 Schemas, routes, dependency and constraints regeneration (Python 3.12/3.14). 9 Docs, final diff, full suite.

## Risks
Format drift (parser fails loudly); understated cost basis without fees; breaking changes to the 001 manual API and holdings
shape; partial histories quarantine an ISIN; O(n^2) per-row fold (5,000-row safety cap, not a performance guarantee);
the framework may not support the 2 MB streaming rule through `UploadFile` (spike first).
