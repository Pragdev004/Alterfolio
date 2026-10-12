# Feature 001: Trade ledger and holdings

Status: APPROVED (plan review, 2026-10-11). Sources: `docs/design.md`, `docs/spec.md`, `docs/v1-lineage.md`, V1 `API.md`
(field optionality only). Tags: `[D#]` decision made in this plan; everything else is already decided by the project.

## Scope
In: `domain/` (enums incl. `MarketSession`, `Instrument`, numeric constants); `users` + `trades`; user-scoped repository;
pure holdings fold; ledger service (record, correct, void, list, get); routes; Alembic initial revision; tests.
Out: import (feature 002), quotes and summary (003), `quant/`, `ai/`, frontend, real auth, corporate actions.
Covers FR-1, 1a, 2, 6, 7, 10, 11 [D1]. `investment_horizon` (V1) is dropped; it is not in FR-1.

## Decisions
- D2 Cost basis (decided by the owner at the release gate; supersedes the earlier price-only draft): BUY brokerage and
  taxes are added to acquisition cost, so `invested_amount` and `average_buy_price` include them. SELL brokerage and
  taxes reduce net sale proceeds and realized P&L and never change the remaining average cost. All Decimal.
  Realized P&L (net proceeds, cost of sold, P&L per instrument, fully exited ones included) is computed by the pure
  fold only; it is not exposed by any route in 001 (summary is 003).
- D3 Test DB: in-memory SQLite (StaticPool, `PRAGMA foreign_keys=ON`, `create_all`) with portable types in
  `app/db/types.py` (exact decimal text and aware-UTC variants for SQLite). Dedupe index declared with both
  `postgresql_where` and `sqlite_where`. Live Postgres tests run only if `ALTERFOLIO_TEST_DATABASE_URL` is set.
- D4 Current user: dependency `get_current_user_id` returns one configured id (default UUID constant, env-overridable).
  No header, no client `user_id`. Idempotent `ensure_user` at startup. Route tests override the dependency.
- D5 Decimal: `domain/numeric.py` constants `MONEY_CONTEXT = Context(prec=28, ROUND_HALF_EVEN)`, `SCALE = 6`. Columns
  `NUMERIC(20,6)`. More than 6 decimals is rejected, never rounded. Derived values quantized to 6 dp once at the API
  boundary. A full exit sets quantity and invested to exactly 0.
- D6 Deps: lower-bound ranges, no lockfile. Runtime: fastapi, sqlalchemy>=2.0, alembic, pydantic>=2, pydantic-settings,
  psycopg[binary]>=3.1. Dev: pytest>=8, httpx.
- D7 Paths: no version prefix. Added `POST /trades/{id}/correct`, `POST /trades/{id}/void`,
  `GET /portfolio/holdings?as_of=`. Absent `as_of` = all effective trades (no clock read).
- D8 Errors: business-rule rejections are 422; unknown or another user's id is 404. Domain errors use
  `{"detail": {"code", "message"}}` with codes `oversell`, `already_superseded`, `trade_not_found`, `invalid_trade`, `duplicate_trade`,
  `numeric_limit_exceeded`.
- D9 Order: canonical key `(trade_timestamp, side_rank, recorded_at, id)`, BUY before SELL at equal timestamps.
  `GET /trades` orders by `(trade_timestamp, recorded_at, id)`; holdings by `(symbol, exchange)`. Injected clock and id
  factory.
- D10 Correction: target any of the user's rows with no superseder (else 422); correction may change any FR-1 field;
  `user_id` immutable; new row has source MANUAL and `recorded_at` = now; body is a full replacement. Composite FK
  `(user_id, supersedes_trade_id)` -> `(user_id, id)`.
- D11 Validation: quantity > 0, price > 0, fees and taxes >= 0, finite, <= 6 decimals, JSON numbers rejected for decimal
  fields, aware timestamp, non-empty symbol and name, exact enums. Symbol stored verbatim (canonicalization is FR-9).
  Required: symbol, name, asset_type, exchange, side, quantity, price_per_unit, trade_timestamp, market_session.
  Defaults: currency INR, fees 0, taxes 0, status EXECUTED. Optional: broker, order_id, broker_trade_id, notes.
  `source` is server-set (MANUAL). Service `TradeInput` is the single validation authority; DB CHECKs are the last guard.
  Release-review additions: text lengths from `domain/limits.py` (also the column sizes); `MAX_AMOUNT` = 10^15 bounds each
  trade (checked exactly in `EXACT_CONTEXT`) and every fold running total; manual duplicate `(broker, broker_trade_id)`
  originals are 422 `duplicate_trade` (pre-check plus savepointed insert; the unique index is the race-safe backstop;
  broker '' counts as a value, only NULL escapes). Round 3: NUL rejected in text fields; Decimal exponent as written must
  lie in [-20, 13] (`MIN/MAX_INPUT_EXPONENT`), zero included. Final review: `trade_timestamp` UTC instant must lie in
  `limits.MIN/MAX_TRADE_TIMESTAMP` (a day inside the calendar edges; UTC overflow is a 422, not a 500).
- D12 Back-dated writes: create, correct and void share one check: fold the candidate effective set per affected
  instrument in canonical order; reject if any prefix goes negative. Rejected writes change nothing.
- D13 `GET /portfolio/holdings` ships in 001; fully exited instruments are omitted.

## Superseded by Feature 002 (see `002-zerodha-tradebook-import.md`, `002a`, `002b`)
- D7 routes: `POST /trades` and `/correct` now require `isin` (BREAKING); `/correct` takes `TradeCorrectionIn`; all write
  routes can return 409 `ledger_busy`.
- D11 required fields: `isin` is required; imported trades may have NULL `name`, `asset_type`, `market_session`.
- D12 identity: the fold and oversell check group by ISIN (`HoldingKey`), not `(symbol, exchange)`; legacy NULL-ISIN rows
  stay separate. Dedupe index now includes `exchange`.
- D13 holdings shape: `{isin, listings, name, quantity, average_buy_price, invested_amount, cost_basis_complete}`.
- D8 gains `ledger_busy` and `invalid_import_file`. "Concurrent-write locking" below is resolved by 002 OPEN-11.

## Still TBD
Corporate actions; symbol canonicalization (003); as-known-at-date queries; real auth; API versioning and pagination
(`GET /trades` returns all rows, history included); concurrent-write locking; voiding an already CANCELLED row (allowed,
no-op for holdings); V2 success sentence.

## Data model
`users(id, created_at)`. `trades`: id, user_id, symbol, name, asset_type, exchange, currency (INR), side, quantity,
price_per_unit, brokerage_fee, taxes (NUMERIC(20,6)), trade_timestamp, recorded_at, broker, broker_trade_id, order_id,
supersedes_trade_id, source, market_session, status, notes. Constraints: `unique(user_id, id)`;
`unique(supersedes_trade_id)`; composite same-user FK; partial dedupe index; CHECKs (quantity, price, fees, taxes, enums,
currency); index `(user_id, trade_timestamp)`. A mapper-level guard raises on UPDATE or DELETE of `Trade`.
Fold: BUY adds quantity and `quantity x price + fee + taxes` to cost; SELL cuts cost by `average x qty`; sell equal to held sets 0; sell
above held is an oversell. Effective set = EXECUTED rows with no superseding row.

## API
Decimals are strings; timestamps ISO-8601; user from `get_current_user_id`.
| Route | Out | Errors |
| --- | --- | --- |
| `GET /health` | `{"status":"ok"}` (no DB) | none |
| `POST /trades` | 201 Trade | 422 |
| `POST /trades/{id}/correct` (full body) | 201 new Trade | 404, 422 |
| `POST /trades/{id}/void` | 201 CANCELLED Trade | 404, 422 |
| `GET /trades` | all user rows | none |
| `GET /trades/{id}` | Trade | 404, 422 bad uuid |
| `GET /portfolio/holdings?as_of=` | holdings, `[]` if empty | 422 naive or bad `as_of` |

## Boundaries
- `domain/`: enums, `Instrument`, numeric constants. stdlib only.
- `repositories/trade_repository.py`: `add`, `get`, `list_for_user`, `list_effective`, `superseder_of`; `user_id` is a
  required keyword everywhere; no update or delete method.
- `services/holdings.py`: pure (no sqlalchemy, fastapi, pydantic, clock). `services/ledger.py`: `TradeInput`,
  `LedgerService(repo, clock, id_factory)`; `services/errors.py`. Services never import `schemas` or `api`.
- `schemas/`, `api/`: parse, call service, map errors, quantize; per-request unit of work. `create_app(...)` only, run with
  `uvicorn app.api.main:create_app --factory`.
- Import-test edges added: `api -> schemas`, `schemas -> domain`, `services -/-> schemas`.

## Tests (no env file, no credentials)
Boundaries (domain, quant, ai, holdings purity, no float in money paths); Decimal (round trip, >6 dp, JSON number, full
exit); time (naive, offset, inclusive as-of, later trades do not change as-of); ordering (equal timestamps, shuffled
insertion); append-only (no mutating method, ORM guard, correction leaves original identical, void, double correction,
chain, cross-user, composite FK); oversell (direct, back-dated, correction, void, unchanged rows on reject); holdings
(hand-computed, NSE vs BSE, empty); isolation at repository, service, route; settings (`create_app` without `.env`);
migration (offline `alembic upgrade head --sql`; live only under `ALTERFOLIO_TEST_DATABASE_URL`).

## Order
1 deps, conftest, boundary tests. 2 domain. 3 holdings fold. 4 db types, models, repository. 5 ledger service.
6 schemas, api, config. 7 Alembic revision. 8 docs and `CLAUDE.md`, final diff, full suite.

## Verification status (2026-10-11, final review pass)
Fresh venvs outside the repo, installed with the documented command and `constraints.txt` (SQLAlchemy 2.1.4, pydantic 2.14.0,
pytest 9.1.1, fastapi 0.143.0): Python 3.14.5 and 3.12.10 freeze identically, `pip check` clean; default suite 286 passed,
49 skipped; live PostgreSQL 16.14 suite (fresh throwaway database, dropped) 335 passed on both. Live tests cover NUMERIC(20,6),
timestamptz under five session timezones, dedupe index, same-user FK, CHECKs, append-only guard, the real startup path,
and the API end to end. PostgreSQL 17 not exercised. Python 3.11 unverified.

## Risks
SQLite variant types remain the test-only design risk (mitigated by the live PostgreSQL tests when a URL is set); no hash
pinning in `constraints.txt`; the test client emits an `httpx` deprecation warning.
