# Alterfolio V2 - Spec

Source tags: `[U#]` user decision from the Day 0 interview (see `docs/v1-lineage.md`); `[U-approved]` commitment the
user approved on review of the design; `[V1:file]` taken from a V1 doc and approved with this spec at the Design Gate;
`TBD` unresolved. Law numbers in tags refer to the V2 constitution unless prefixed V1.

## Problem
User: an individual retail investor trading NSE/BSE equities and ETFs in INR `[U4]`. Pain, from V1 PRD: investors
know the outcome of the decisions they made and lack structured, reproducible numbers about their own portfolio
`[V1:PRD.md]`. V2 positioning is portfolio + quant analytics; AI only interprets structured quant output `[U2]`.
Core principle (user brief): financial truth belongs to deterministic domain/quantitative code; the AI layer must
not become the source of financial truth.
Success in one sentence: TBD (the V1 pain statement is twin-framed; the V2 sentence needs the user's wording).

## v1 scope (stages, in build order)
1. Core portfolio / trades / assets foundation, including Zerodha tradebook import `[U6]`.
2. Quant V1: market data, returns, volatility, drawdown, risk metrics on the user's own portfolio `[U5]`.
3. Analytics UI over stages 1-2 (deterministic observations included `[V1:ADR 009]`).
4. Quant V2: pairs, cointegration, strategy, sizing `[U5]`.
5. Backtesting: execution model, backtester loop, evaluation, walk-forward `[U5]`.
6. AI layer: interprets structured quant output only.
7. Advanced research/signals: sealed ledger, bias cost, skill-vs-luck, replay report are candidates `[U6]`.
Only stage 1 is detailed below. Stages 2-7 get their own plan file before any code (C8 in the lineage register).

Out of scope for v1:
- Twin portfolio, twin BUY/SELL/HOLD decisions, twin replay `[U2]`.
- Asset types beyond equities and ETFs, currencies other than INR `[U4]`.
- Real multi-user auth, cloud deployment, Azure `[U7]`.
- Order execution on behalf of users, financial advice `[V2 Law 6]`.

## Functional requirements (stage 1 detail)
- FR-1: Record a trade manually with the V1 field set (symbol, name, asset type, exchange, side, quantity, price,
  timestamp, fees, taxes, broker, order id, source, session, status) `[V1:API.md]`. The system adds `recorded_at`.
- FR-1a: Correct a trade by recording a new row that supersedes the original (`supersedes_trade_id`); void a trade
  with a superseding row of status CANCELLED. Trades are never updated or deleted `[U-approved]`.
- FR-2: List trades and fetch one trade by id `[V1:API.md]`.
- FR-3: Import a Zerodha Console tradebook CSV into trades with source = import, scoped to the user `[V1:build-plan M1]`.
- FR-4: Re-importing the same file creates no new rows. Dedupe uses `broker_trade_id` (the broker's per-fill id),
  not `order_id`, because partial fills share an order id `[V1:build-plan M1, U-approved]`.
- FR-5: Import returns counts of imported, duplicate and rejected rows, with a reason per rejected row `[V1:build-plan M1]`.
- FR-6: Reconstruct holdings per instrument from trades (quantity, average buy price, invested amount) `[V1:API.md]`.
  Buy-side brokerage and taxes are part of acquisition cost (average buy price, invested amount). Sell-side brokerage
  and taxes reduce net sale proceeds and realized P&L and do not change the remaining average cost `[U-approved]`.
  Realized P&L is computed in the pure fold; no route exposes it in feature 001.
- FR-7: Reconstruct holdings as of a past timestamp using only trades at or before it `[V1:current-state.md]`.
- FR-8: Portfolio summary: total trades, total invested, per-holding rollup, valuation status
  (COMPLETE, PARTIAL, UNAVAILABLE) `[V1:API.md, ADR 009]`.
- FR-9: Fetch current quotes through a market-provider abstraction; NSE and BSE symbol handling `[V1:market-data.md]`.
- FR-10: Every trade, holding and summary is scoped to the user; isolation is tested at repository, service and
  route level `[U7, V1:CLAUDE.md]`.
- FR-11: The AI layer is absent from stage 1; no stage 1-5 code imports AI code `[V2 Law 7]`.

## Data (stage 1)
| Entity | Key fields | Rules |
| --- | --- | --- |
| Trade | id, user_id, symbol, name, asset_type, exchange, currency, side, quantity, price_per_unit, trade_timestamp, recorded_at, brokerage_fee, taxes, broker, broker_trade_id, order_id, supersedes_trade_id, source, market_session, status, notes | Append-only, never updated or deleted; Decimal money and quantity; timestamps tz-aware UTC; currency INR; unique `(user_id, broker, broker_trade_id)` among original rows only; a row is superseded at most once |
| Holding (derived) | symbol, exchange, quantity, average_buy_price, invested_amount | Recomputable from trades; never hand-edited |
| MarketQuote | symbol, exchange, price, price_timestamp, source | A missing price is never estimated |
| ImportResult | file name, imported, duplicates, rejected[row, reason] | Re-import is idempotent |
Enums carried from V1 `[V1:API.md]`: asset_type limited to STOCK and ETF in v1 `[U4]`; exchange NSE, BSE; side BUY, SELL;
source MANUAL, IMPORT; status EXECUTED, PENDING, CANCELLED, REJECTED. Other V1 values are out of scope.

## Contracts (stage 1, from V1 and TBD for V2 paths)
| Endpoint / screen | Input | Output | Errors |
| --- | --- | --- | --- |
| POST /trades | Trade fields | Trade with id and timestamps | 422 on validation |
| GET /trades, GET /trades/{id} | optional id | Trade list or one Trade | 404 unknown id, 422 bad UUID |
| POST /imports/tradebook | Zerodha CSV file | imported / duplicates / rejected counts with reasons | 422 unreadable file |
| GET /portfolio/summary | none | total trades, total invested, holdings, valuation status | Missing quotes appear as valuation PARTIAL/UNAVAILABLE, not hidden |
| GET /health | none | status ok | none |
Feature 001 adds (see `docs/plans/001-trade-ledger-holdings.md`): `POST /trades/{id}/correct`, `POST /trades/{id}/void`,
`GET /portfolio/holdings?as_of=`. Business-rule errors are 422 with `{"detail": {"code", "message"}}`; another user's id is 404.
Versioning is still TBD.

## Edge cases and error handling
- Sell larger than held quantity -> rejected; the real ledger stays long-only `[V1:research-accounting.md]`.
- Naive (timezone-less) timestamp -> rejected `[V1:market-data.md]`.
- Malformed CSV row -> counted as rejected with a reason; other rows still import `[V1:build-plan M1]`.
- Same broker trade id imported twice -> duplicate, not a new row `[V1:build-plan M1]`.
- Partial fills of one order (same `order_id`, different `broker_trade_id`) -> separate trades, all imported.
- Correction that would make any later sell exceed holdings -> rejected `[U-approved]`.
- Correcting a trade twice -> rejected; correct the latest superseding row instead.
- Quote missing for a holding -> valuation PARTIAL; market-value figures are not computed from guesses `[V1:ADR 009]`.
- Empty portfolio -> zeros and an empty holdings list, not an error `[V1:progress 2026-10-08]`.
- Trade with BSE and NSE listing of the same company -> separate instruments (identity = `(symbol, exchange)`).
- Corporate actions, splits and dividends -> TBD, not specified in V1 docs.
- Duplicate `(broker, broker_trade_id)` among a user's original rows on manual create -> 422 `duplicate_trade`; the unique
  index stays the race-safe final enforcement. Corrections may keep the original's ids.
- Text longer than its column (symbol 64, name 256, broker 64, broker_trade_id 128, order_id 128, notes 2000 characters)
  -> 422 `invalid_trade`, never truncated. NUL characters in any text field are rejected the same way (PostgreSQL cannot
  store them). An empty-string broker is a value for duplicate detection, like the unique index; only NULL escapes it.
- Decimal inputs must carry an exponent within [-20, 13] as written, zero included (so `0E+1000000` and a value with
  thousands of trailing zeros are rejected, not normalized): 422 `invalid_trade`.
- `trade_timestamp` must be an instant between 0001-01-02T00:00Z and 9999-12-30T23:59:59.999999Z (one day inside the
  calendar edges, so reads in any session timezone stay representable); outside it, or an offset that overflows UTC -> 422.
- A trade whose quantity x price + fees + taxes, or any running total (held quantity, cost, net proceeds, cost sold)
  per instrument, reaches 10^15 -> 422 `numeric_limit_exceeded`; never rounded or clamped.

## Constraints
- Stack: FastAPI, PostgreSQL via SQLAlchemy, React + TypeScript + Vite, Python 3.11+ `[U3]`.
- Tests run without a database configuration and without AI credentials `[V1:C7, V2 Law 7]`.
- Single user, local first; no deadline assumed; deployment decided after stage 3 `[U7]`.
- Educational platform, not financial advice; no profitability claims `[V2 Laws 6, 8]`.
- Markdown docs under 200 lines; never push without approval; one plan file per feature.
- Money and quantity are Decimal everywhere (string in JSON); float only inside statistics `[U-approved]`.
- Shared enums and `Instrument` live in a stdlib-only `app/domain/`; `app/quant/` imports no framework or ORM `[U-approved]`.

## Open questions (carried to design)
1. One-sentence success statement for V2.
2. Frontend/design-system direction (no V1 design doc exists; frontend skills decide in design).
3. Corporate actions (splits, bonuses, dividends) handling.
4. Market-data provider beyond Yahoo, and whether to persist a bar cache.
5. As-known-at-date queries (need `recorded_at` filtering; not in v1).
Resolved: trade correction policy (FR-1a); instrument identity = `(symbol, exchange)`; constitution wording
(8 laws, see `docs/design.md`).

## Acceptance criteria (stage 1 is done when)
Feature split: 001 = isolation, point-in-time, oversell, append-only/correction, hand-computed holdings, import-boundary,
no-DB-env suite; 002 = parser, duplicate-import, partial-fill; 003 = summary and quotes.
- [ ] Parser tests pass on a fixture CSV with buys, sells, partial fills, NSE and BSE rows and one malformed row.
- [ ] A duplicate-import test shows zero new rows on re-import.
- [ ] Isolation tests pass at repository, service and route level.
- [ ] A point-in-time test shows holdings as of T are unchanged when later trades are added.
- [ ] A sell larger than held quantity is rejected by a test.
- [ ] Tests show trades have no update or delete path, a correction supersedes without editing the original, and an
      oversell-causing correction is rejected.
- [ ] A partial-fill import test shows several fills with one `order_id` all import, and re-import adds none.
- [ ] Holdings and summary values match hand-computed examples.
- [ ] The full test suite passes with no database env file and no AI credentials.
- [ ] An import-boundary test fails if any non-AI module imports AI code.
