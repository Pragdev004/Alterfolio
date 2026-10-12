# Feature 002a: Owner decisions (Zerodha import)

Companion to `002-zerodha-tradebook-import.md` (flow, mapping, API) and `002b-schema-api-tests.md` (schema, 001 contract
changes, holdings semantics, tests, doc checklist). All items below were decided by the owner on 2026-10-11 unless marked
"derived". Status: all of these decisions are now implemented (see `docs/specs/002-*.md`); the text below is unchanged.

## Identity and holdings
- OPEN-1 ISIN is the canonical instrument identity for holdings. Exchange is trade-level metadata. The same security on NSE
  and BSE is one holding when the ISIN matches. Holdings fold and oversell check group by ISIN.
- 1a Empty/missing ISIN in a file row -> rejected `missing_isin`; no symbol/exchange fallback; row not stored; no quarantine.
- ISIN format: exactly 12 ASCII characters matching `[A-Z0-9]`; lowercase or non-ASCII is rejected, never normalized; no
  check-digit validation. Applies to manual create, correction and import.
- 1b (1) ISIN is REQUIRED on all new manual trades and corrections (`POST /trades`, `/correct`): an intentional BREAKING
  change to the 001 manual API. (2) Existing NULL-ISIN trades stay in the append-only ledger and appear as separate holdings
  grouped by `(symbol, exchange)` with `isin: null`, explicitly flagged; never merged into an ISIN holding; resolved by a
  correction that supplies the ISIN; never excluded, never blocking the holdings endpoint.
- 1c An ISIN holding displays `isin`; `listings` = distinct `{symbol, exchange}` pairs among ALL its effective trades at or
  before `as_of`, sorted deterministically; `name` = the most recent such trade with a non-null name (else null). No preferred
  exchange, no per-exchange quantity. The as-of rule applies to the position AND the metadata. NULL-ISIN holdings keep their
  `(symbol, exchange)` identity (single listing).
- 1d Holdings item replaces top-level `symbol`/`exchange` (no dual shape): `{isin|null, listings:[{symbol, exchange}],
  name|null, quantity, average_buy_price, invested_amount (strings), cost_basis_complete}`. `cost_basis_complete` = false if
  any effective trade in the CURRENT POSITION EPOCH (after the last point the quantity was zero, as of `as_of`) has
  `charges_provided=false`. Sell-side missing charges do not count (they affect proceeds, not remaining cost). Order: ISIN
  ascending, then NULL-ISIN by `(symbol, exchange)`. `as_of`, string decimals, `[]` when empty, fully exited omitted: unchanged.

## Dedupe and duplicates
- OPEN-2 Unique key `(user_id, broker, exchange, broker_trade_id)`, original rows only (`broker_trade_id IS NOT NULL AND
  supersedes_trade_id IS NULL`); `broker_trade_id` stays the raw Zerodha `trade_id`. Same id on NSE and BSE = different trades.
- OPEN-6 Key match and all comparable source-provided fields equal -> `duplicate`; any differs -> `conflicting_duplicate`,
  counted under `rejected`. The original row is never overwritten; comparison is against the ORIGINAL row (never a correction
  or void). Comparable: isin, symbol, side, quantity, price (numeric equality), UTC timestamp, order_id (not name/type/session/
  fees). When the existing row has NULL for a comparable field, that field does not create a conflict. Within one file: first
  occurrence in file order kept; identical repeat = `duplicate`; differing repeat = `conflicting_duplicate`.
- OPEN-7 Quarantine: canonical-order processing; after the first `oversell` for an ISIN in an import, later rows of that ISIN
  in the same import are rejected `after_oversell`; other ISINs continue; earlier rows of that run stay. Rejected rows leave
  no record; no automatic opening balance, no estimation. Re-import after the missing history is loaded imports them.
  7a Duplicate/conflict classification runs BEFORE quarantine; quarantine applies only to genuinely new rows.

## Fields the source does not provide
- OPEN-3 `name`, `asset_type`, `market_session` are nullable for imported trades (NULL = not provided). Manual trades still
  require them. No derivation of `market_session`, no instrument map, no `name=symbol`/`STOCK` defaults.
- 3a Correction = full replacement, null-tolerant: `isin` always required; `name`/`asset_type`/`market_session` may stay null
  only where the target's value is null; a known value is never erased to null; nothing derived or invented. If the target has
  `charges_provided=false`, `brokerage_fee` and `taxes` MUST be explicit in the body (explicit 0 = affirmed known zero); for
  `charges_provided=true` targets the 001 defaults and validation are unchanged. A correction always creates a new row with
  `charges_provided=true`.
- H-4 `void` copies the target row (NULLs and `charges_provided` included), needs no ISIN, sets status CANCELLED,
  `import_batch_id` NULL.
- OPEN-4 Imports store `brokerage_fee = 0`, `taxes = 0` (fold unchanged) and set `trades.charges_provided=false`. Manual rows
  and corrections store true. The import response reports `fees_taxes_provided: false`. Cost basis is understated and
  realized P&L overstated until corrected; docs must say so.

## Parsing, limits, upload
- OPEN-5 `order_execution_time` is fixed IST (+05:30, no DST, no tzdata) converted to UTC. Only `YYYY-MM-DDTHH:MM:SS`;
  missing, date-only, fractional seconds or any zone/offset -> `invalid_timestamp`; no midnight fallback. `trade_date` must
  equal the IST date, else `date_mismatch`. The 001 timestamp window applies after conversion.
- OPEN-8 Max 2 MB, max 5,000 data rows (a safety limit, NOT a performance guarantee); over either -> whole-file 422
  `invalid_import_file`, never truncated. Response lists the first 200 rejections plus `rejected_total`. `file_name`: base name,
  <= 255, no control/NUL, audit only. UTF-8 (optional BOM) else 422; comma CSV, standard quoting, blank lines skipped.
  Header: exactly the 13 columns, case-insensitive, any order, trimmed; missing/extra/duplicate column or header-only -> 422.
- OPEN-9 multipart/form-data; add `python-multipart`, regenerate `constraints.txt`, verify on fresh venvs Python 3.12 and
  3.14 (install command, `pip check`, full suite).
- A-4 Exactly one part named `file`. Missing file, extra parts/form fields, malformed multipart, missing/empty filename (after
  basename reduction), empty file, and any file-level transport/parsing failure -> 422 `invalid_import_file`, nothing persisted.
  The part content-type is not validated. The 2 MB limit is enforced WHILE reading the request, never after buffering the whole
  file. If `UploadFile` cannot satisfy this, use a streaming `request.stream()` approach with `python-multipart` and map every
  multipart parse failure to `invalid_import_file`. The 2 MB requirement is not weakened for framework defaults.
- OPEN-12 Series: only `EQ` on NSE and `A` on BSE; anything else -> `unsupported_series` (observed value in the detail); no
  ISIN quarantine.

## Batches, transactions, locking
- OPEN-10 FILE-level failures (bad header/encoding, empty, over limits, multipart failures) -> 422, no batch, no trades.
  ROW-level results never fail the file: a valid upload ALWAYS creates a batch (even all-duplicate/all-rejected) and returns
  201. Batch stores file_name, SHA-256 (NOT unique), total_rows, imported, duplicates, rejected_total, user_id, `created_at`
  (injected clock); rejected rows not persisted. `trades.import_batch_id` nullable, same-user composite FK: set on imported
  trades, NULL on manual trades, corrections and voids.
- OPEN-11 Manual record, import, correct and void each take `SELECT ... FOR UPDATE NOWAIT` on the user's `users` row at the
  start of the write transaction (`with_for_update(nowait=True)`; no-op on SQLite, verified in live PostgreSQL tests). Lock held
  -> 409 `ledger_busy`; never an indefinite wait.
