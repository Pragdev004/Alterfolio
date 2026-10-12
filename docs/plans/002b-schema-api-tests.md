# Feature 002b: Schema, 001 contract changes, semantics, tests, docs

Companion to `002-zerodha-tradebook-import.md` and `002a-decisions.md` (owner decisions, referenced as OPEN-#/1a-1d/3a/A-4/H-4).
Items tagged [derived] follow mechanically from those decisions but were chosen while writing this plan; review them.

## Schema: migration `0002` (one revision, nothing backfilled)
- `import_batches(id, user_id FK, file_name, file_sha256, total_rows, imported, duplicates, rejected_total, created_at)`;
  `UNIQUE(user_id, id)` for the composite FK; no unique on `file_sha256`; `user_id` indexed.
- `trades` adds: `isin` NULL (legacy rows stay NULL); `charges_provided` boolean NOT NULL, existing rows true; `import_batch_id`
  NULL with composite FK `(user_id, import_batch_id) -> import_batches(user_id, id)`.
- `trades.name`, `asset_type`, `market_session` become nullable (their enum CHECKs already pass NULL).
- Dedupe index `uq_trades_dedupe` dropped and recreated on `(user_id, broker, exchange, broker_trade_id)` with the same
  partial predicate, for both `postgresql_where` and `sqlite_where`.
- [derived] CHECKs (portable): `isin IS NULL OR length(isin) = 12`; `(source = 'IMPORT') = (import_batch_id IS NOT NULL)`
  written as a boolean expression valid on SQLite and PostgreSQL. Format `[A-Z0-9]` is enforced by the service validator (the
  001 single validation authority), not by a dialect-specific regex CHECK.
- [derived] Downgrade removes the new table/columns/index and restores the old index; restoring NOT NULL fails loudly if NULL
  rows exist and never rewrites data. The existing migration test runs upgrade/downgrade on an empty database.
- Append-only guard unchanged; no UPDATE/DELETE path is added.

## 001 contract changes (consolidated; breaking where noted)
- `POST /trades` (`TradeIn`): adds REQUIRED `isin` (BREAKING); everything else as 001. `status`, `source`, `charges_provided`,
  `import_batch_id` are server-set; manual rows store `charges_provided=true`.
- `POST /trades/{id}/correct`: body `TradeCorrectionIn` [derived], distinct from `TradeIn`: `isin` required;
  `name`/`asset_type`/`market_session` optional in the schema; `brokerage_fee`/`taxes` `Decimal | None = None` so "omitted" is
  distinguishable from an explicit 0. The service validates against the target row per 3a and rejects with 422 `invalid_trade`
  (never erasing known values, never defaulting fees when the target has `charges_provided=false`).
- `POST /trades/{id}/void`: unchanged request; copies the target per H-4.
- `TradeOut` adds `isin`, `charges_provided`, `import_batch_id`; `name`, `asset_type`, `market_session` become nullable.
- `GET /portfolio/holdings`: new item shape per 1d (BREAKING). Other routes unchanged.
- Errors: add 409 `ledger_busy` (all write routes) and `LedgerBusyError`; the error map gains it. Existing codes unchanged.
- [derived] One validation authority: manual `TradeInput` and the import input share the same validator functions (text,
  decimal, ISIN, timestamp window), so rules cannot drift; the import input only relaxes the three nullable fields and fixes
  fees to 0.

## Holdings and oversell semantics
- [derived] `HoldingKey` (domain, stdlib): the ISIN for ISIN holdings, or `(None, symbol, exchange)` for legacy rows;
  `Instrument(symbol, exchange)` stays as the listing value object. `LedgerEntry` gains `isin`, `name`, `charges_provided`.
  `fold_ledger`/`find_oversell`/`Holding` key by `HoldingKey`; `list_effective` filters by keys, not `(symbol, exchange)`.
- Oversell check (D12) re-folds every affected key: for a correction, the candidate's key AND the replaced row's key (a legacy
  row corrected to an ISIN moves quantity between keys; both are re-checked). NULL-ISIN and ISIN holdings never offset each
  other. A legacy NULL-ISIN sell is covered only by NULL-ISIN buys of the same `(symbol, exchange)`.
- Epoch: the position epoch starts after the latest canonical-order entry at or before `as_of` that left the key's quantity at
  zero. `cost_basis_complete` considers the epoch's effective BUYs only (sell-side charges never count); `listings`/`name` use all effective trades at or
  before `as_of`. "Most recent" = last in canonical order `(trade_timestamp, BUY first, recorded_at, id)`.
- [derived] `listings` sort key `(exchange.value, symbol)`. Realized P&L stays computed by the fold per key, not exposed.

## Import pipeline details [derived]
- Per row, in this order: (1) parse and validate (codes below); (2) key match -> `duplicate` or `conflicting_duplicate`
  (7a); (3) ISIN quarantine (`after_oversell`); (4) oversell fold -> `oversell`; (5) insert. A row invalid in step 1 is
  `rejected` even if its key matches an existing row.
- Lock order: read and parse the upload (bounded), then take the user lock, then insert the batch and rows. A held lock returns
  409 before anything is written (no batch). A missing `users` row is a 500 (startup seeds it); not a business error.
- Lost unique-index race: re-query the winner by key and re-classify (`duplicate` or `conflicting_duplicate`); never assume.
- Repository: `original_by_key(user_id, broker, exchange, broker_trade_id)` returns the original row for comparison.
- Row numbers: 1-based FILE LINE where the record starts (header = line 1); `total_rows` counts data records excluding blank
  lines; `rejected` is listed in ascending line order. Canonical import order breaks ties by `int(trade_id)`.
- Required columns must be non-empty except `isin` (-> `missing_isin`); any other empty value -> `missing_field`.
- Normative row codes: `unsupported_exchange`, `invalid_side`, `invalid_number` (non-decimal text), `invalid_timestamp`,
  `date_mismatch`, `unsupported_segment`, `unsupported_auction`, `unsupported_series`, `missing_isin`, `missing_field`,
  `invalid_trade` (any other 001 rule), `numeric_limit_exceeded`, `conflicting_duplicate`, `oversell`, `after_oversell`.
  File-level: `invalid_import_file`. `duplicate` is a count, not a rejection.

## Tests (synthetic data only; real files never committed or read by default)
- Parser/format: header variants, every column format, 6 dp values kept verbatim, 7 dp/exponent/sign/NaN rejected, IST->UTC,
  `date_mismatch`, segment/auction/series/exchange/side rejections, ISIN `[A-Z0-9]` (lowercase, non-ASCII, length), empties.
- Multipart/limits: streaming 2 MB stop (never buffer first), 5,000 rows, missing/extra/malformed parts, empty/missing
  filename, wrong content-type; a spike test proves the streaming approach before the route is built.
- Dedupe: key includes exchange (SQLite and PostgreSQL); re-import zero rows; sequential/overlapping files; other user
  independent; NULL-existing-field rule; conflicting duplicate in file and vs DB; manual-vs-import; corrected/voided original;
  lost race re-classified.
- Holdings: ISIN grouping across exchanges, NULL-ISIN separate and flagged, listings/name/as_of, `cost_basis_complete` with
  epoch reset, ordering, shape, `[]`, exited omitted, hand-computed values, point-in-time.
- Oversell: NSE buy then BSE sell; quarantine of one ISIN only; back-dated vs manual; legacy-to-ISIN correction re-check;
  rejected rows leave no record; re-import after loading history imports them.
- Corrections: 3a matrix (isin required, nulls kept only where null, known values not erased, fees explicit when
  `charges_provided=false`, defaults unchanged otherwise, new row true); void copy incl. `charges_provided`.
- Transactions/locking: file-level failures create no batch; row rejections never fail the file; batch counts and invariant
  `imported + duplicates + rejected_total == total_rows`; mid-file failure rolls back rows and batch; live-PostgreSQL lock test
  (409 `ledger_busy`, import vs manual write); `import_batch_id` isolation across users.
- Migration: offline SQL render, upgrade/downgrade on empty DB, new CHECKs, new index; live PostgreSQL tests when the URL is set.
- Existing 001 tests to update for the breaking changes: `test_api`, `test_ledger_service`, `test_holdings`,
  `test_trade_repository`, `test_migration`, `test_postgres_integration`, `test_import_boundaries` (parser purity edges),
  `test_repo_hygiene` (add the no-tracked-tradebook-CSV guard).

## Documentation changes (at implementation approval)
Status: DONE. The items below were applied to the listed files (as-built specs: `docs/specs/`); the checklist is kept as approved.
- `docs/design.md`: data model (trade fields, dedupe index, identity line 70, `import_batches`), decision table (dedupe row),
  commitments (line 177), Main flow 1, domain boundary text.
- `docs/spec.md`: FR-3..FR-6, entities (Trade, Holding, ImportResult), contracts table, edge cases (lines 80, 85, 87),
  open question 3, acceptance criteria wording.
- `CLAUDE.md`: Project Context status, Architecture identity line 42, dedupe line 48, input-limit line 53, Commands
  (python-multipart), Context Map (002, 002a, 002b), Critical Rules unchanged.
- `docs/plans/001-...md`: note superseded items (D7 routes, D11 required fields, D13 holdings shape, D12 identity).
- `docs/v1-lineage.md`: register the new owner decisions. All Markdown files stay under 200 lines.
