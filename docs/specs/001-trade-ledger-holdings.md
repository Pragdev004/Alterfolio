# Spec 001: Trade ledger and holdings

Status: delivered. Plan: `docs/plans/001-trade-ledger-holdings.md`. Feature 002 changed parts of it (marked "002 changes");
all of those are now built and described in `002-4-import-service.md` and `002-5-api-and-holdings.md`, which win over this file.

## Purpose
Record an investor's NSE/BSE trades in an append-only ledger and derive holdings from it, for one user, API only. Holdings
are computed, never stored. All money is `Decimal`.

## Behavior
- **Record** a trade (`POST /trades`). Required: symbol, name, asset_type, exchange, side, quantity, price_per_unit,
  trade_timestamp, market_session. Defaults: currency INR, fees 0, taxes 0, status EXECUTED. Optional: broker, order_id,
  broker_trade_id, notes. `source` is MANUAL and server-set. (002 changes: `isin` is required, see `002-5`.)
- **Correct** (`POST /trades/{id}/correct`): full replacement body; creates a new row with `supersedes_trade_id`. The target
  must have no superseder (else 422 `already_superseded`). The original row is never edited.
- **Void** (`POST /trades/{id}/void`): creates a CANCELLED row copying the target and superseding it.
- **List / get** (`GET /trades`, `GET /trades/{id}`): `GET /trades` returns all of the user's rows, including history,
  ordered by `(trade_timestamp, recorded_at, id)`. Unknown or another user's id is 404.
- **Holdings** (`GET /portfolio/holdings?as_of=`): effective trades (EXECUTED and not superseded), folded per
  holding key (002 changes: one holding per ISIN, legacy NULL-ISIN rows per `(symbol, exchange)`; new response shape in `002-5`). Fully exited holdings are omitted; no trades gives `[]`. `as_of` must be timezone-aware; absent means
  all effective trades and the clock is not read. Decimals are strings.
- **Health** (`GET /health`): `{"status":"ok"}`, no database.

## Rules
- Append-only: no update or delete path in the repository, and a mapper-level guard raises on UPDATE/DELETE of `Trade`.
- Effective set: EXECUTED rows that no other row supersedes. A row is superseded at most once.
- Fold order: `(trade_timestamp, BUY before SELL, recorded_at, id)`.
- Cost basis: BUY fees and taxes join acquisition cost (`average_buy_price`, `invested_amount` include them). SELL fees and
  taxes reduce net proceeds and realized P&L only. A sell equal to the held quantity sets quantity and cost to exactly 0.
  Realized P&L exists in the fold but no route exposes it.
- Long-only: a create, correct or void that would make any prefix of the candidate effective set negative is rejected
  (422 `oversell`) and changes nothing.
- Duplicate original `(user_id, broker, broker_trade_id)` on manual create is 422 `duplicate_trade`; corrections may reuse
  the original's ids. (002 changes: the key gains `exchange`; built in Step 4.)
- Validation (single authority: `TradeInput`): quantity > 0, price > 0, fees and taxes >= 0, finite, at most 6 decimal
  places, exponent as written in [-20, 13], naive timestamps rejected, text lengths from `domain/limits.py`, NUL rejected,
  `trade_timestamp` inside the `limits` window after UTC conversion, `quantity x price + fees + taxes` and every running total
  below `MAX_AMOUNT` (10^15, `numeric_limit_exceeded`). Nothing is rounded, clamped or truncated.
- Errors: business rules are 422 `{"detail": {"code", "message"}}` (codes `oversell`, `already_superseded`,
  `trade_not_found`, `invalid_trade`, `duplicate_trade`, `numeric_limit_exceeded`); unknown id 404.
- Isolation: every repository method takes a required keyword `user_id`; the current user comes from the
  `get_current_user_id` dependency (one configured id), never from the request.

## Data
`users(id, created_at)`; `trades` with the FR-1 fields, `recorded_at`, `supersedes_trade_id`, `source`, `status`, NUMERIC(20,6)
money columns. Constraints: unique `(user_id, id)`, unique `supersedes_trade_id`, composite same-user FK for supersession,
partial dedupe index, CHECKs for quantity, price, fees, taxes, enums and currency. Migration `0001`.

## Code map
`app/domain/` (enums, `Instrument`, `numeric`, `limits`), `app/services/holdings.py` (pure fold), `app/services/ledger.py`
(`TradeInput`, `LedgerService`), `app/repositories/trade_repository.py`, `app/models/`, `app/schemas/trade.py`,
`app/api/` (factory `create_app`, routes, deps), `app/db/column_types.py`.

## Verification
- Tests: `test_domain`, `test_holdings`, `test_trade_repository`, `test_ledger_service`, `test_api`, `test_migration`,
  `test_startup`, `test_smoke`, `test_import_boundaries`. They cover hand-computed holdings, point-in-time, oversell,
  append-only, isolation at repository, service and route level, and the AST layering rules.
- Recorded at release (2026-10-11): 286 passed on Python 3.14.5 and 3.12.10, and a live PostgreSQL 16 run of 335 passed. That
  was before Feature 002; the current suite is in `002-3-import-persistence-foundation.md`.

## Known limits
No corporate actions, no quotes or summary (003), no real auth, no pagination or API versioning, symbol canonicalization
deferred, PostgreSQL 17 and Python 3.11 not exercised.
