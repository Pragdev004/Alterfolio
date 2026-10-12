# Spec 002-2: Zerodha tradebook CSV parser

Status: delivered; pure, not wired to persistence. Plan: `002-zerodha-tradebook-import.md` and `002b-schema-api-tests.md`.
Code: `backend/app/services/tradebook_parser.py`. Tests: `tests/test_tradebook_parser.py`, `tests/test_import_boundaries.py`,
`tests/test_repo_hygiene.py`. Fixture: `tests/fixtures/tradebook_synthetic.csv` (synthetic only).

## Purpose
Turn the bytes of a Zerodha Console equity tradebook into validated row values or per-row rejections. No database, FastAPI,
pydantic, clock or I/O (checked by an AST test).

## Interface
`parse_tradebook(content: bytes, *, max_rows=5000) -> ParseResult(total_rows, rows, rejections)`.
- `ParsedTradeRow(line, symbol, isin, exchange, side, quantity, price_per_unit, trade_timestamp, broker_trade_id, order_id, broker)`;
  `broker` is the constant `ZERODHA`; timestamps are timezone-aware UTC; quantity and price are `Decimal` kept verbatim.
- `RowRejection(line, code, message)`; `line` is the 1-based physical file line (header is line 1). Blank lines are skipped
  and are not data rows.

## File-level failures (raise `InvalidImportFileError`, 422 `invalid_import_file`)
Not UTF-8; no header; header only; header is not exactly the 13 columns `symbol, isin, trade_date, exchange, segment, series,
trade_type, auction, quantity, price, trade_id, order_id, order_execution_time` (any order and case, trimmed; missing, extra or
duplicate column fails); malformed CSV (strict); a row whose cell count differs from the header; more than 5,000 data rows.

## Row rules, checked in this order (first failure wins)
1. Empty `isin` -> `missing_isin`. Any other empty cell -> `missing_field`.
2. `unsupported_exchange` (only NSE, BSE); `invalid_side` (`buy`/`sell`, case-folded); `unsupported_segment` (only `EQ`);
   `unsupported_series` (`EQ` on NSE, `A` on BSE); `unsupported_auction` (only `false`).
3. `invalid_trade`: ISIN not `[A-Z0-9]{12}`; symbol over 64; trade_id not digits or over 128; order_id over 128 or NUL.
4. Numbers: plain unsigned decimal only. Exponent, sign, NaN, Infinity, more than 6 decimal places -> `invalid_number`.
   Zero or more than 14 integer digits -> `invalid_trade`.
5. `order_execution_time` must be `YYYY-MM-DDTHH:MM:SS` and inside the 001 timestamp window after conversion, else
   `invalid_timestamp`. It is fixed IST (+05:30) converted to UTC. A bad `trade_date` shape or impossible date is
   `invalid_timestamp`; a `trade_date` that differs from the IST date is `date_mismatch`.
6. `quantity x price` of 10^15 or more -> `numeric_limit_exceeded`.

Rejected rows never stop the file. Duplicate detection, oversell and quarantine are not part of the parser.

## Privacy
No real tradebook data is in the repository. A hygiene test fails if any tradebook-like CSV other than the synthetic fixture
is tracked, and checks the fixture's values are synthetic.

## Verification
`test_tradebook_parser.py` has 198 tests covering the header contract, every column, the rejection taxonomy and the fixture.
Full suite after Step 4: 568 passed, 50 skipped on Python 3.14.5 and 3.12.

## Known limits
Validators duplicate some rules of `TradeInput` (a shared validator was deferred). Within-file duplicate handling, dedupe
against the ledger, quarantine and persistence belong to the import service (not built).
