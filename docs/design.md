# Alterfolio V2 - Design

Status: APPROVED at the Design Gate (2026-10-08); current source of truth. Tags: `[U#]` user decision from the interview, `[U-approved]`
architectural commitment the user approved on review, `[V1:...]` inherited candidate (see `docs/v1-lineage.md`),
`[NEW]` proposed here with no V1 source. Spec: `docs/spec.md`.

## Objective
A portfolio and quantitative analytics platform for an individual NSE/BSE investor (equities and ETFs, INR). It
records trades, reconstructs holdings, computes portfolio risk metrics, later runs pairs research and backtests,
and finally lets an AI layer explain structured quant output. Financial truth belongs to deterministic
domain/quant code; the AI layer interprets structured output and is never the source of a number.

## Tech stack
| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI `[U3]` | Same as V1; numpy 2.x already needs 3.11+ |
| Database | PostgreSQL, SQLAlchemy 2, Alembic `[U3]` | Same as V1; Decimal-exact NUMERIC columns |
| Quant | Pure Python package; statsmodels isolated to one adapter `[V1:ADR 003]`; shared types from `app/domain/` | Keeps the boundary testable |
| Frontend | React + TypeScript + Vite, vitest `[U3]` | Same as V1 |
| Market data | Provider interface, Yahoo adapter first `[V1:C6]` | Swappable; second provider TBD |
| AI | Provider-neutral port, none by default `[V1:P1]` | Stage 6; provider chosen by ADR then |
| Tests | pytest with no DB env file, vitest `[V1:C7]` | A fresh clone must run the suite |

## Architecture
Dependency direction (arrows = "may import"); anything not listed is forbidden and checked by an import test:
```
api -> services -> repositories -> models
services -> quant            (pure functions and value objects)
services -> providers        (market data)
ai   -> quant result schemas (read-only; stage 6)      api -> ai (stage 6)
domain -> stdlib only                                  every layer MAY import domain
quant -> stdlib + domain + statsmodels adapter only    quant NEVER -> api, services, repositories, models, db,
                                                       ai, providers, or any framework/ORM
```
Proposed layout (`backend/app/`): `domain/` (shared enums and `Instrument`), `api/`, `services/` (portfolio, imports,
analytics), `repositories/`, `models/`, `schemas/`, `providers/market/`, `quant/{market_data,features,risk,pairs,
strategy,sizing,execution,backtest,evaluation}/`, `ai/` (stage 6). `quant/` is top-level, not under `services/` as in
V1 `[U-approved]`, because it is a layer boundary. `domain/` replaces V1's one documented exception (quant importing
`app.models.enums`) and prevents duplicating the same concepts inside quant. Frontend:
`frontend/src/{app,features/<feature>,shared/{api,ui,hooks,lib,theme}}` `[V1:CLAUDE.md]`.
Stage 1 is API-only; UI starts at stage 3.
Implemented edges not drawn above (plan 001): `services -> models` (read types), `api -> schemas`, `api -> db` (session
factory), `schemas -> domain`; `services` never import `schemas` or `api`. Tests use in-memory SQLite with portable
Decimal/UTC column types; the server runs on PostgreSQL only.

`domain/` rules: standard library only; no framework, ORM, I/O, clock or settings; holds shared enums (Exchange,
AssetType, Currency, TradeSide, TradeStatus, TradeSource) and value objects (`Instrument`). Anything with behavior
beyond validation of its own fields belongs in `quant/` or `services/`, not `domain/`.

## Domain boundaries
1. **Accounting** (stage 1): trades, holdings, valuation. Long-only, Decimal, user-scoped, append-only.
2. **Quant** (stages 2, 4, 5): market data, features, risk, pairs, strategy, sizing, execution, backtest,
   evaluation. Pure. Never reads or writes live user tables; research portfolios use their own signed accounting
   `[V1:P7]`. Inputs arrive as value objects supplied by `services/`.
3. **AI** (stage 6): reads structured quant/accounting outputs, writes only prose. No write path, no calculation.

## Data model direction (stage 1 detail; later stages TBD)
- `trades`: append-only `[U-approved]`. Fields per spec, plus `broker_trade_id` (nullable, the broker's per-fill id),
  `recorded_at` (when the row was entered; `trade_timestamp` is when the trade happened), `supersedes_trade_id`
  (nullable FK to trades). NUMERIC for money and quantity, `timestamptz` UTC, `user_id`. No UPDATE or DELETE code path.
- Import dedupe: partial unique index on `(user_id, broker, broker_trade_id)` WHERE `broker_trade_id IS NOT NULL AND
  supersedes_trade_id IS NULL`, so it applies to original rows only. `order_id` is stored but never used for dedupe
  (partial fills share an order id). Replaces the earlier `order_id` key.
- Corrections `[U-approved]`: a new row with `supersedes_trade_id` and the corrected values; a void is a correcting
  row with status CANCELLED. A row is superseded at most once (unique on `supersedes_trade_id`), chains are allowed,
  and the correction must share the original's `user_id`. The effective trade set = EXECUTED rows not superseded.
  A correction is rejected if re-folding the effective set would oversell at any point. As-known-at-date queries
  (filtering `recorded_at`) are not in v1; `recorded_at` is stored so they stay possible.
- `import_batches`: user_id, file name, file SHA-256, counts, created_at `[NEW]`.
- Instrument identity = `(symbol, exchange)` plus asset_type and currency as columns on the trade; no instruments
  table in stage 1; NSE and BSE listings are distinct `[V1:quant-domain.md]`. Corporate actions are out of stage 1.
- Holdings, summaries, observations, quant metrics: derived, not stored `[V1:quant-domain.md]`.
- Market bars: fetched on demand, not cached; `DataProvenance` + fingerprint recorded with any stored result
  `[V1:ADR 002]`. Quant result persistence is decided per stage plan, with the first schema at stage 5 (BacktestRun).
- One `users` row for the single user; every user-owned table carries `user_id` `[U7]`.

## Quant engine architecture
- Flow `[V1:quant-domain.md]`: MarketBar -> MarketSeries -> features -> (risk metrics | pairs -> strategy ->
  sizing) -> execution -> backtest -> evaluation. Stage 2 builds market_data, features, risk; stage 4 pairs,
  strategy, sizing; stage 5 execution, backtest, evaluation, walk-forward `[U5]`.
- Contracts: Strategy, PositionSizer, ExecutionModel are Protocols; Backtester owns the loop only `[V1:P8]`.
- Point-in-time: `truncated_to(T)` is the only narrowing; every layer ships a future-data-cannot-change-result test.
- Determinism: no clock reads, no unseeded randomness inside `quant/`; results carry config + provenance.
- Undefined values are `None` or `Unavailable(reason)`; never NaN, inf or silent zero `[V1:P6]`.
- Output contract `[NEW]`: every public quant result is a frozen, versioned dataclass with a JSON-serialisable form
  (`schema_version`, `as_of`, `provenance`, `inputs`, `values`). Stage 6 consumes exactly this form.
- Port selectively `[U1]`: V1 modules are copied only when their stage starts, with their tests, and re-reviewed.

## AI architecture (stage 6; nothing built before)
- Port `Explainer` (or the V1 `IAgentOrchestrator` shape) in `app/ai/`; adapters per provider; default = none.
- Input: versioned structured quant outputs only. Output: prose that cites field ids from the input.
- Numeric guard `[NEW]`: every number in AI text must match a value in the input payload; otherwise the response is
  rejected, not shown. Tools are read-only over computed results. AI cannot call services that write.
- Unconfigured AI returns an explicit 503 `ai_provider_not_configured`; never a fabricated or substitute answer `[V1:P1]`.
- Orchestration framework (LangGraph or plain loop) and provider are chosen by an ADR at stage 6 `[V1:ADR 010 style]`.

## Frontend and design-system direction
React + TypeScript feature folders. Visual direction is NOT set yet: before stage 3 UI work, a `DESIGN.md` is
produced using the frontend design skills (frontend-design-defaults baseline), and charts follow the dataviz skill.
Deterministic observations use factual wording and review triggers, never BUY/SELL `[V1:ADR 009]`.

## Numeric policy (decides V1 caveat C1) `[U-approved]`
Any money, price, quantity, cash, fee, tax, notional or P&L value is `Decimal` in memory, `NUMERIC` in PostgreSQL
and a string in API JSON. Float is allowed only for statistical estimates (returns, volatility, z-scores,
regression and test statistics) and dimensionless ratios. A float becomes a Decimal at most once, at a function
boundary, with an explicit rounding rule; a Decimal never round-trips through float. A full exit closes the exact
held Decimal quantity; no dust tolerance. One Decimal context (precision, rounding) is set once and documented.
Quantity from notional uses Decimal with an explicit rounding rule (TBD at stage 4). The frontend never holds money
as a JS `number`.

## Constitution revision `[U8, approved by the user]`
Approved diff; written to `docs/constitution.md` at scaffold with the exact wording shown in the V1 -> V2 diff.
V2 has 8 laws; retired V1 numbers 3 and 7 are not kept.
| V2 law | From V1 | Change |
| --- | --- | --- |
| Purpose | Purpose | Revised: portfolio and quant analytics platform, not an AI twin |
| 1 No Future Knowledge | 1 | Subject reworded: no computation, simulation or signal uses information unavailable at its as-of time |
| 2 Declared Inputs | 2 | Revised: simulations start from explicitly declared inputs recorded with the result |
| 3 Traceability | 4 | Revised: every computed result, signal and AI statement is traceable to named inputs and rule |
| 4 Separate Simulations | 5 | Revised: simulated portfolios are separate from the real ledger; never read or write it |
| 5 Immutable History | 6 | Subject reworded; added: a correction is a new superseding record, never an edit |
| 6 Educational Purpose | 8 | Unchanged |
| 7 Provider-Neutral AI | 9 | Added: financial truth comes only from deterministic code; AI cannot become its source |
| 8 Human-Centric Design | 10 | Subject reworded |
| (removed) | 3 Independent Decisions, 7 Continuous Reflection | Dropped: twin-only laws |

## Invariants (engineering constraints)
1. `quant/` imports only stdlib, `app/domain/` and the statsmodels adapter; never api, services, repositories,
   models, db, ai, providers or any framework/ORM (AST import test over the whole package). `domain/` imports
   stdlib only (same test).
2. No non-AI module imports `app/ai/`; tests pass with no AI credentials and no DB env file.
3. Money is Decimal; timestamps tz-aware UTC; naive timestamps rejected.
4. Trades are append-only; derived state is recomputable from them.
5. Point-in-time tests exist for every as-of computation.
6. No silent repair, estimation or fallback price; unavailable is explicit.
7. Every user-owned read and write is user-scoped and has an isolation test.
8. No profitability claims; thresholds are labelled research parameters.
9. Each feature has a plan file before code; docs stay under 200 lines.

## Design decisions
| Decision | Chosen | Rejected alternatives | Why |
| --- | --- | --- | --- |
| V1 reuse | Port selectively `[U1]` | Full rewrite; copy whole engine | Reuse proven pure code without inheriting float and scope debt |
| Product | Portfolio + quant analytics `[U2]` | AI twin; skill-vs-luck replay | Matches the supplied stage order and the AI-last principle |
| Quant location | `app/quant/` top-level | `services/quant/` (V1) | Boundary is a layer; simpler import rule |
| Shared types | stdlib-only `app/domain/` (enums, `Instrument`) | Quant imports `models` (V1 exception); duplicate enums in quant | One definition, no ORM in quant, no drift |
| Import dedupe key | `broker_trade_id`, partial unique on original rows | `order_id` (partial fills collide) | Matches the spec; corrections cannot collide |
| Trade edits | Append-only with supersede link, `recorded_at` | In-place update; hard delete | Immutable history, auditable corrections |
| Instrument table | Columns on trade, no table in stage 1 | Instruments table now | Corporate actions deferred; avoid premature schema |
| Bar cache | None; provenance fingerprint | Persisted cache now | V1 judged it unjustified; revisit on restated data |
| Numeric type | Decimal end to end, float only in statistics | Float notionals (V1); dust tolerance | Removes the exit-residue bug class |
| AI output | Cited prose + numeric guard | Free-form text; AI computing numbers | Enforces the core principle |
| Auth | Single user, scoped model `[U7]` | Real auth now | Not needed locally; keeps isolation tests |
| Stage 1 UI | None (API only) | Minimal UI in stage 1 | Spec lists UI at stage 3 |

## Main flows
1. Tradebook import: upload CSV -> parse rows -> validate (tz, side, Decimal) -> dedupe on broker trade id ->
   insert -> `ImportResult` counts with per-row rejection reasons.
2. Holdings as of T: select user's trades with timestamp <= T and not superseded -> fold with weighted-average
   cost -> holdings; sells above held quantity are rejected.
3. Portfolio summary: holdings -> provider quotes -> valuation status (COMPLETE/PARTIAL/UNAVAILABLE) -> summary;
   missing quotes are reported, never estimated.
4. Stage 6 explanation: quant result (versioned JSON) -> Explainer -> prose with field citations -> numeric guard.

## Development plan
| Phase | Delivers | Gate to next phase |
| --- | --- | --- |
| 1 | Portfolio, trades, assets, Zerodha import, holdings, summary (API) | Spec stage-1 acceptance criteria all green |
| 2 | Quant V1: market data, features, portfolio risk metrics | Point-in-time and hand-computed tests; import test |
| 3 | Analytics UI + `DESIGN.md` + observations | vitest behaviour tests; build passes; rendered check |
| 4 | Quant V2: pairs, cointegration, strategy, sizing | Statistical tests on synthetic data; ADRs recorded |
| 5 | Backtesting: execution, loop, evaluation, walk-forward | Leakage tests; trial counts recorded |
| 6 | AI layer (provider ADR first) | Numeric guard tests; works with AI off |
| 7 | Advanced research/signals | Per-feature plan and approval |

## Architectural commitments approved at the Design Gate
1. Append-only trades with `supersedes_trade_id`, `broker_trade_id` dedupe, `recorded_at`.
2. Decimal for money and quantity; float only inside statistics.
3. Top-level `app/quant/` plus stdlib-only `app/domain/`.
4. Constitution diff (8 laws).

## Still TBD (not blocking the gate)
Success sentence for V2; visual design direction (`DESIGN.md` before stage 3); market-data provider beyond Yahoo;
corporate actions; quantity rounding rule (stage 4); as-known-at-date queries.
