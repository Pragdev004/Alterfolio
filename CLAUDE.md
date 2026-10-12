# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Project Context
Alterfolio V2: portfolio + quantitative analytics platform for an individual NSE/BSE investor (equities and ETFs, INR).
Records trades, reconstructs holdings, computes risk metrics, later pairs research/backtests, finally an AI layer that
only explains structured quant output. **Financial truth comes only from deterministic domain/quant code; AI is never
a source of a number.** Educational, not financial advice; no profitability claims.

Status: Feature 001 (trade ledger + holdings, API only) implemented per `docs/plans/001-trade-ledger-holdings.md`;
feature 002 (Zerodha import, plans `docs/plans/002*.md`, as-built specs `docs/specs/`) is implemented and verified (API, holdings,
live PostgreSQL 16.14 suite); 003 (quotes + summary) is not started. `quant/` is an empty package; no frontend.
V1 lives read-only at `C:\Users\praga\Desktop\projects 2\alterfolio` and is ported
selectively, only when a stage starts (see `docs/v1-lineage.md`).

Source of truth (read before designing): `docs/design.md` (approved 2026-10-08), `docs/spec.md` (stage-1 FRs,
acceptance criteria). Tags `[U#]`/`[U-approved]`/`[V1:...]` there mark provenance of each decision.

Stages: 1 portfolio/trades/Zerodha import -> 2 Quant V1 (risk) -> 3 analytics UI -> 4 Quant V2 (pairs) ->
5 backtesting -> 6 AI layer -> 7 advanced research. Only stage 1 is specified in detail.

## 2. Architecture
Dependency direction (anything not listed is forbidden; enforced by an AST import test):
```
api -> services -> repositories -> models
services -> quant, services -> providers (market data)
(implemented extras, see plan 001: services -> models for read types; api -> schemas, db; schemas -> domain only)
ai -> quant result schemas (stage 6);  api -> ai (stage 6)
domain: stdlib only; every layer may import it
quant: stdlib + domain + one statsmodels adapter ONLY (never api/services/repositories/models/db/ai/providers/ORM)
```
- `backend/app/domain/`: shared enums (Exchange, AssetType, Currency, TradeSide, TradeStatus, TradeSource,
  MarketSession), `Instrument`, and `numeric.py` constants (`MONEY_CONTEXT`, `SCALE=6`). No framework, ORM, I/O, clock.
- `backend/app/quant/`: pure, deterministic (no clock, no unseeded randomness). Flow: MarketBar -> MarketSeries ->
  features -> risk | pairs -> strategy -> sizing -> execution -> backtest -> evaluation. Inputs arrive as value
  objects from `services/`; quant never reads user tables.
- Built: `api/` (factory `create_app`, routes), `services/` (`holdings.py` pure fold, `ledger.py`), `repositories/`,
  `models/`, `schemas/`, `db/` (`column_types.py` portable Decimal/UTC types). Planned: `providers/market/`, `ai/`;
  frontend `frontend/src/{app,features/<feature>,shared/...}` (stage 3).
- Three domain boundaries: Accounting (real ledger, long-only, append-only) / Quant (pure) / AI (read-only prose).
  Simulated portfolios never read or write the real ledger.
- Holding identity = ISIN (002): NSE and BSE listings of one ISIN are one holding; legacy NULL-ISIN trades are separate,
  flagged holdings keyed by `(symbol, exchange)`. `Instrument(symbol, exchange)` is the listing value. No instruments table.

### Trade ledger model (cross-cutting)
- `trades` is append-only: no UPDATE/DELETE code path. Correct = new row with `supersedes_trade_id`; void = superseding
  row with status CANCELLED. A row is superseded at most once. Effective set = EXECUTED rows not superseded.
- A correction that would make any later sell exceed holdings is rejected. Sells above held quantity are rejected.
- Import dedupe key = `(user_id, broker, exchange, broker_trade_id)` (partial unique index, original rows only). Never
  dedupe on `order_id` (partial fills share it). Imported rows have `charges_provided=false` (fees/taxes unknown, stored 0).
- `trade_timestamp` (when it happened) vs `recorded_at` (when entered). Holdings/summaries are derived, never stored.
- Missing quote -> valuation PARTIAL/UNAVAILABLE; never estimate a price.
- Input limits (reject, never truncate/round): text lengths in `domain/limits.py`; each trade amount and every holdings
  running total < `MAX_AMOUNT` (10^15, `domain/numeric.py`); duplicate manual `(broker, exchange, broker_trade_id)` -> 422; no NUL in
  text; Decimal exponent as written within [-20, 13] (zero included); `trade_timestamp` within `domain/limits.py` window;
  tradebook upload <= 2 MiB (enforced while streaming) and <= 5,000 rows, else 422 `invalid_import_file`.

## 3. Code Style
- Python 3.11+. Money, price, quantity, fee, tax, notional, P&L = `Decimal` in memory, `NUMERIC` in PostgreSQL,
  string in API JSON. Float only for statistics (returns, vol, z-scores, regressions) and dimensionless ratios.
  Never round-trip Decimal through float; convert float->Decimal at most once with an explicit rounding rule.
- Timestamps are tz-aware UTC; reject naive timestamps.
- Undefined quant values are `None` or `Unavailable(reason)`; never NaN, inf, or silent zero.
- Public quant results are frozen, versioned dataclasses with a JSON form (`schema_version`, `as_of`, `provenance`,
  `inputs`, `values`). Strategy, PositionSizer, ExecutionModel are Protocols; Backtester owns the loop only.
- Point-in-time: `truncated_to(T)` is the only narrowing.
- No silent repair, estimation, or fallback values; unavailable must be explicit.
- Observation wording is factual with review triggers, never BUY/SELL.

## 4. Preferred Libraries
Backend: FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL, pytest. Quant: stdlib, statsmodels isolated to one adapter.
Market data: provider interface, Yahoo adapter first. Frontend (stage 3): React + TypeScript + Vite, vitest.
AI provider/orchestration: TBD via ADR at stage 6 (provider-neutral port, default none).
Declared in `backend/pyproject.toml` (setuptools build; runtime incl. `python-multipart` for the streaming tradebook upload;
`dev` extra: pytest, httpx, uvicorn). Exact versions
for the whole closure are pinned in `backend/constraints.txt` (resolved on Python 3.14.5).

## 5. Commands
Run from `backend/` (pytest config: `testpaths=["tests"]`, `pythonpath=["."]`). Fresh-clone install:
```
python -m venv .venv                      # then activate: .venv\Scripts\Activate.ps1 (PowerShell) | source .venv/bin/activate
python -m pip install -c constraints.txt -e ".[dev]"   # deterministic: exact pins; verified on Python 3.14 and 3.12
python -m pytest                          # full suite
python -m pytest tests/test_smoke.py      # one file
python -m pytest tests/test_x.py::test_y  # single test
uvicorn app.api.main:create_app --factory # needs ALTERFOLIO_DATABASE_URL (PostgreSQL only; SQLite is test-only)
alembic upgrade head                      # or: alembic -x url=<pg url> upgrade head --sql  (offline render)
```
Tests use in-memory SQLite and need no env file. `ALTERFOLIO_TEST_DATABASE_URL` (an EMPTY throwaway database) enables
the live-PostgreSQL migration/integration tests; they refuse to run if `users`/`trades` already exist. Python 3.11 is
declared (`>=3.11`) but unverified. Regenerate pins: fresh venv, `pip install -e ".[dev]"`, `pip freeze --exclude-editable`.
Lint/type-check/frontend commands: TBD (not configured yet).

## 6. Critical Rules
1. `quant/` and `domain/` import boundaries (above) are hard rules, checked by an AST import test over the package.
2. No non-AI module imports `app/ai/`. Tests must pass with no DB env file and no AI credentials (fresh clone runs).
3. Every user-owned read/write is `user_id`-scoped and needs an isolation test at repository, service, and route level.
4. Every as-of computation needs a point-in-time test (future data cannot change the result).
5. Unconfigured AI returns explicit 503 `ai_provider_not_configured`; AI text must pass a numeric guard (every number
   matches the input payload) or be rejected.
6. Each feature gets a plan file in `docs/plans/` before code; stages 2-7 need their own plan before any code.
7. Port V1 code only when its stage starts, with its tests, and re-review it (V1 used float notionals; V2 does not).
8. Open/TBD, do not assume: V2 success sentence, corporate actions (splits/bonuses/dividends), non-Yahoo provider,
   quantity rounding rule (stage 4), as-known-at-date queries, frontend `DESIGN.md` (needed before stage 3 UI).
9. Never commit `.env` files or secrets (`.env.example` is allowed).

## 7. Context Map
- `docs/design.md`: architecture, data model, numeric policy, invariants, decision table, development plan.
- `docs/spec.md`: problem, FRs, data entities, endpoint contracts, edge cases, acceptance criteria.
- `docs/v1-lineage.md`: V1 -> V2 register and user decisions U1-U10.
- `docs/plans/001-trade-ledger-holdings.md`: Feature 001 decisions D1-D13, data model, API, tests (002 supersedes some).
- `docs/plans/002-zerodha-tradebook-import.md` (scope, format, flow, API), `002a-decisions.md` (owner decisions OPEN-#),
  `002b-schema-api-tests.md` (migration, 001 contract changes, semantics, tests). `docs/reports/` empty.
- `docs/specs/`: as-built specs per delivered feature (`README.md` index; 001, 002-1 to 002-5). They win over plans where they differ.
- `docs/constitution.md`: 8-law V2 constitution; to be written at scaffold (does not exist yet).
- `.claude/settings.local.json`: local permissions only; `.claude/agents/` and `.claude/hooks/` are empty.
- Obsidian project knowledge: `Alterfolio V2/` in the `obsidian_pragadeeshwar_os` MCP vault.
  Use it as supplemental context for decisions, research, history, and progress not already
  captured in repository docs. Prefer `docs/` and current code as the source of truth for
  implementation and approved design. Read only the notes relevant to the current task;
  never mix knowledge from other project folders. Do not write to Obsidian unless explicitly
  asked or the task requires a documented context update.

## 8. Git Workflow
Branch `main`; Feature 001 is committed (`0df5c49`); Feature 002 is implemented and verified in the working tree, pending review
and commit. Never push without explicit user approval. Markdown docs must stay
under 200 lines. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
