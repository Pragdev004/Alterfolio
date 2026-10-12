# Spec 002-5: Import route, manual API changes and ISIN-grouped holdings

Status: delivered (Step 6). Plan: `002-zerodha-tradebook-import.md`, `002a-decisions.md` (1a-1d, 3a, H-4, OPEN-10/11),
`002b-schema-api-tests.md`. Code: `app/api/routes/{imports,trades,portfolio}.py`, `app/api/{deps,main}.py`, `app/schemas/{trade,imports}.py`,
`app/services/{ledger,holdings}.py`. Tests: `test_api_imports`, `test_api_manual`, `test_api`, `test_holdings`, `test_ledger_service`,
live-only additions in `test_postgres_integration`. No migration.

## Import route
`POST /imports/tradebook` (multipart, exactly one part named `file`). The handler only streams the upload with
`read_tradebook_upload` (2 MiB enforced while reading, no `UploadFile`), then calls `TradebookImportService.import_tradebook` in the
thread pool. It returns 201 with `import_batch_id, file_name, file_sha256, total_rows, imported, duplicates, rejected_total,
rejected[{row, code, message}] (first 200), quarantined_isins, fees_taxes_provided` (always false). `row` is the 1-based file line.
`imported + duplicates + rejected_total == total_rows` is checked by the service and again by the response schema.
- A valid upload always creates a batch, even when every row is a duplicate or rejected.
- File-level failures (transport, encoding, header, limits, filename) are 422 `invalid_import_file` and create nothing. Parsing
  happens before the user lock, so a bad file is 422 even while another write holds the lock.
- A held user lock is 409 `ledger_busy` on the import and on `POST /trades`, `/correct` and `/void`; no batch or trade is written.

## Manual trade API
- `POST /trades` (`TradeIn`): `isin` is required (missing field: pydantic 422; wrong format: 422 `invalid_trade`). Format is exactly
  12 ASCII `[A-Z0-9]`, never normalized. Name, asset type and market session are still required. Rows store `charges_provided=true`.
- `POST /trades/{id}/correct` (`TradeCorrectionIn`, full replacement): `isin` required. `name`, `asset_type`, `market_session` may be
  omitted or null only where the target's value is null; a known value is never erased (422). If the target has
  `charges_provided=false`, `brokerage_fee` and `taxes` must both be stated (explicit `"0"` counts; omitted and JSON null do not).
  Otherwise omitted fees default to 0. The new row is MANUAL, `import_batch_id` NULL, `charges_provided=true`. Service type:
  `CorrectionInput`; validation is shared with `TradeInput` through one function.
- `POST /trades/{id}/void`: unchanged request; copies the target including `isin` and `charges_provided`; MANUAL, no batch, CANCELLED.
- There is no update or delete route (405).
- `TradeOut` adds `isin`, `charges_provided`, `import_batch_id`; `name`, `asset_type`, `market_session` are nullable so imported rows
  list and fetch normally. Decimals stay strings.
- Legacy NULL-ISIN rows stay valid and appear with `isin: null`; the API cannot create new ones.
- Oversell is checked per holding key (ISIN, else legacy listing) for create, correct and void, for the candidate and the replaced row.

## Holdings (`GET /portfolio/holdings?as_of=`)
One item per holding: `{isin | null, listings:[{symbol, exchange}], name | null, quantity, average_buy_price, invested_amount (strings),
cost_basis_complete}` (breaking change from `{symbol, exchange, ...}`).
- Identity: the ISIN; NSE and BSE trades of one ISIN are one holding. NULL-ISIN rows form separate holdings keyed by `(symbol, exchange)`
  (single listing, `isin: null`) and are never merged into an ISIN holding or offset an ISIN sell.
- `listings`: distinct `(symbol, exchange)` of ALL effective trades at or before `as_of`, sorted by `(exchange, symbol)`; this includes
  exchanges traded only in an earlier, exited position. `name`: the last trade in canonical order with a non-null name, else null.
- `cost_basis_complete`: false if any BUY since the position last reached exactly zero has `charges_provided=false`. A partial sell does
  not reset it; a full exit does. SELL charges never count. `as_of` filters the trades first, so position and metadata share it.
- Order: ISIN ascending, then legacy holdings by `(symbol, exchange)`. Fully exited holdings are omitted; no holdings gives `[]`.
- Implementation: `LedgerEntry` carries `isin`, `name`, `charges_provided`; `fold` groups by `HoldingKey` by default (the `group_key`
  override from Step 5 still works and agrees). `Holding` is `{key, listings, name, quantity, average_buy_price, invested_amount,
  cost_basis_complete}`; realized P&L is keyed the same way and is not exposed.

## Verification
Python 3.14.5 and 3.12: 757 passed, 58 skipped; `pip check` clean. The 58 skips are live-PostgreSQL tests, now including: import route end to
end (session used across the thread pool), real `NOWAIT` 409 on import and on manual write routes, and void of an imported row.
Unverified on PostgreSQL: all of those, the lock semantics, and the thread-pool session use. SQLite tests prove behavior, not locking.

## Known limits
A correction of an imported row asserts the fees the caller states (including an explicit 0); nothing checks them against the broker.
Holdings still show no prices or P&L (003). The 001 holdings shape is gone; clients must read `listings`.
