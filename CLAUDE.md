# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Project Context
Alterfolio V2: portfolio + quantitative analytics platform for an individual NSE/BSE investor (equities and ETFs, INR).
Records trades, reconstructs holdings, computes risk metrics, later pairs research/backtests, finally an AI layer that
only explains structured quant output. **Financial truth comes only from deterministic domain/quant code; AI is never
a source of a number.** Educational, not financial advice; no profitability claims.

Status: Feature 001 (trade ledger + holdings, API only) implemented per `docs/plans/001-trade-ledger-holdings.md`;
feature 002 (Zerodha import, plans `docs/plans/002*.md`, as-built specs `docs/specs/`) is implemented and verified (API, holdings,
live PostgreSQL 16.14 suite); 003 (market-data port, Yahoo adapter, `GET /portfolio/summary`; plan `docs/plans/003*.md`, spec `docs/specs/003*.md`) is committed; 004 (quant market-data foundation: daily-bar port, Yahoo daily bars, `MarketBar`/`MarketSeries`, market-series service; plan `docs/plans/004*.md`, spec `docs/specs/004*.md`) is committed (`e7010bc`); 005 (backtesting foundation; plan `docs/plans/005*.md`, spec `docs/specs/005*.md`) is implemented and committed (steps 1-6, `acac749` + `55a03de`), awaiting owner review; D7 DECIDED: recorded in result, persisted later (`trial_count`); 009 (RAG date-cutoff; plan `docs/plans/009*.md`, spec `docs/specs/009*.md`) is COMPLETE (owner-verified, live: full suite 2222 passed, 0 skipped). 011 (portfolio analysis wiring: `services/portfolio_analysis.py`, `POST /api/analyst/ask`, offline demo; plan/spec `docs/*/011*`) is implemented, awaiting owner review. 014 (no spec yet): Task 1 (sector map, reference data, +INDIANB/PSB/UCOBANK) done in `1eb8c8a`; Task 2 (NIFTY baseline via `ind_nifty50list` membership) partial; Task 3 (corporate actions) blocked on the NSE corporate-actions CSV. 013a (analysis read API: `GET /api/analysis/{meta,trips,trips/{id},regimes,biases}`, server-side `*_display` strings on every endpoint the UI uses, `answer_source` on `/ask`; plan/spec `docs/*/013a*`) is implemented, awaiting owner review; 013a.1 (reason_text, histogram bins, direction, null counts; one retained field `BaselineOutcome.portfolio_returns` in `quant/luck_test`) is built; 013 (frontend spec + design `docs/design/013-frontend-design.md`) has no app code yet. `quant/` holds `market_data/` and `backtest/`; no frontend code.
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
services -> quant, services -> providers (ports only: `providers/market/port.py`, `providers/market/history_port.py`;
  Feature 009 embeddings: `providers/embedding/port.py`, imported only by `services/retrieval.py`; never an adapter)
(implemented extras, see plan 001: services -> models for read types; api -> schemas, db; schemas -> domain only)
ai -> quant result schemas (stage 6);  api -> ai (stage 6)
analyst (010, service layer): imports domain only (never quant, services, adapters, ORM); langgraph/langchain only in
  `analyst/graph.py`; httpx only in `analyst/llm_openai.py`; nothing in domain/quant/models/repositories/services imports it
domain: stdlib only; every layer may import it
quant: stdlib + domain + one statsmodels adapter ONLY (never api/services/repositories/models/db/ai/providers/ORM)
```
- Display (013a): all rounding and wording for people lives in `domain/display.py` (stdlib only); schemas add `x_display` siblings
  via `schemas/display.py`; analysis JSON is built in `api/analysis_presenter.py` from `services/analysis_view.py` read types
  (`services/analysis_read.py` caches per `(user, as_of, ledger_version)`, no TTL). The frontend never formats a number.
- `backend/app/domain/`: shared enums (Exchange, AssetType, Currency, TradeSide, TradeStatus, TradeSource,
  MarketSession), `Instrument`, and `numeric.py` constants (`MONEY_CONTEXT`, `SCALE=6`). No framework, ORM, I/O, clock.
- `backend/app/quant/`: pure, deterministic (no clock, no unseeded randomness). Flow: MarketBar -> MarketSeries ->
  features -> risk | pairs -> strategy -> sizing -> execution -> backtest -> evaluation. Inputs arrive as value
  objects from `services/`; quant never reads user tables.
- Built: `api/` (factory `create_app`, routes), `services/` (`holdings.py` pure fold, `ledger.py`), `repositories/`,
  `models/`, `schemas/`, `db/` (`column_types.py` portable Decimal/UTC types). `providers/market/` (quote port, daily-bar `history_port`, Yahoo adapter), `quant/market_data/`, `services/market_series.py`. Planned: `ai/`;
  frontend `frontend/src/{app,features/<feature>,shared/...}` (stage 3).
- Three domain boundaries: Accounting (real ledger, long-only, append-only) / Quant (pure) / AI (read-only prose).
  Simulated portfolios never read or write the real ledger.
- Holding identity = ISIN (002): NSE and BSE listings of one ISIN are one holding; legacy NULL-ISIN trades are separate,
  flagged holdings keyed by `(symbol, exchange)`. `Instrument(symbol, exchange)` is the listing value. No instruments table.
- Daily bars (004): provider numbers stay exact Decimals (no rounding; `to_dict`/fingerprint use canonical Decimal text);
  provider timestamps are kept as aware UTC. The service reads its clock once, passes that instant to the provider, requires
  `batch.retrieved_at` to equal it, and a bar is eligible only if its session date is before the exchange-local date of that
  instant. `MarketSeries.truncated_to` only narrows. Detail: `docs/specs/004-quant-market-data-foundation.md`.

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
  string in API JSON. Float only for statistics (returns, vol, z-scores, regressions) and dimensionless ratios;
  Feature 009 retrieval only: embedding vectors and cosine scores in `providers/embedding/ollama.py`,
  `services/retrieval.py`, `repositories/chunks.py`, which may not import money modules (boundary test enforced).
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
Market data: provider port, Yahoo adapter via httpx (runtime dep; httpx imported only in `providers/market/yahoo.py`, `analyst/llm_openai.py` and
`providers/embedding/ollama.py`). Frontend (stage 3): React + TypeScript + Vite, vitest.
Embeddings (009): provider port + local Ollama adapter (`nomic-embed-text`) via httpx; pgvector is a PostgreSQL extension, not a
Python dependency.
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
- `docs/v1-lineage.md`: V1 -> V2 register and user decisions U1-U12.
- `docs/plans/001-trade-ledger-holdings.md`: Feature 001 decisions D1-D13, data model, API, tests (002 supersedes some).
- `docs/plans/002-zerodha-tradebook-import.md` (scope, format, flow, API), `002a-decisions.md` (owner decisions OPEN-#),
  `002b-schema-api-tests.md` (migration, 001 contract changes, semantics, tests). `docs/reports/` empty.
- `docs/specs/`: as-built specs per delivered feature (`README.md` index; 001, 002-1 to 002-5, 003, 004). They win over plans where they differ.
- `docs/constitution.md`: 8-law V2 constitution; to be written at scaffold (does not exist yet).
- `.claude/settings.local.json`: local permissions only; `.claude/agents/` and `.claude/hooks/` are empty.
- Obsidian project knowledge: `Alterfolio V2/` in the `obsidian_pragadeeshwar_os` MCP vault.
  Use it as supplemental context for decisions, research, history, and progress not already
  captured in repository docs. Prefer `docs/` and current code as the source of truth for
  implementation and approved design. Read only the notes relevant to the current task;
  never mix knowledge from other project folders. Do not write to Obsidian unless explicitly
  asked or the task requires a documented context update.

## 8. Git Workflow
Branch `main`; Feature 001 is committed (`0df5c49`); Feature 002 is committed (`e7da01c`); Feature 003 is committed (`0068438`); Feature 004 is committed (`e7010bc`); Feature 005 is committed (steps 1-6: `acac749`, `55a03de`; owner review pending; D7 decided, `trial_count` recorded).
Never push without explicit user approval. Markdown docs must stay
under 200 lines. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## 9. Operating rules
**Operating rules — SPRINT MODE (valid until 2026-10-18, then revert)**
- Inspect the repo before acting; verified repo state beats this handoff.
- Owner approves at spec review, design review, and end of feature only.
- Accept-edits mode permitted. Plans under 10 lines unless writing a design doc.
- Per step: focused tests, then full suite (.venv/Scripts/python.exe -m pytest -q
  from backend/). Commit only when both are green, conventional commits.
  Never push, amend, or add remotes.
- Never weaken or edit an approved test to make code pass; stop and ask instead.
- Never claim a test or inspection you didn't perform. Report discrepancies.
- Every Markdown file stays under 200 lines.
- Feature numbering: 006 bias cost + behaviour profile, 007 luck test, 008 regime
  split, 009 RAG date-cutoff, 010 LangGraph analyst, 011 MCP server, 012 demo
  report. Persistence/trial registry is deferred until after 012.

## 10. Known issues
- Import validates the whole effective ledger in trade-time order, so feasible splits give the same ledger in any upload order.
  A sell uploaded BEFORE its buy is still rejected (`oversell`, long-only rule; quarantine is spec): upload the earlier
  tradebook first, or re-upload the sell file afterwards (converges; tested). `scripts/demo_real.py` merges files and imports once.
- 8 PSU banks in `config/analysis_universe.toml` (PNB, BANKBARODA, UNIONBANK, BANKINDIA, MAHABANK, INDIANB, PSB, UCOBANK): ISINs
  verified against niftyindices (`1eb8c8a`, `isin_source` in the toml); corporate actions still unreviewed (pending 014 Task 3), so
  luck stays Unavailable for them. The other universe ISINs are from memory.
- Nifty 50 membership is not configured (NIFTY baseline Unavailable); no document retriever is wired into the API (`app.state.retriever`).
- niftyindices CSVs are committed; remove and scrub history before making the repo public.
- Declare units for behaviour archetype metrics: `BehaviourProfile.supporting_metrics` are (name, text) pairs with no declared
  unit, so the API shows them labelled `unitless` and never guesses a unit or format.
