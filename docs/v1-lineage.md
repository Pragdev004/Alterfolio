# V1 Lineage Register

V1 repo (read-only source): `C:\Users\praga\Desktop\projects 2\alterfolio\docs`.
V1 documents are source material, not an approved V2 spec. Status values:
- **proposed-inherited**: carried into V2 as a candidate; accepted as part of the Design Gate approval (2026-10-08),
  except where a later stage plan revisits it.
- **changed**: V1 behaviour deliberately not carried over as-is.
- **deferred**: V1 item moved to a later V2 stage.
- **dropped**: not part of V2 v1 scope.

User decisions that shape this register (Day 0 interview, 2026-10-08):
- U1 Port selectively: copy V1 quant code only where a stage needs it and the V2 spec confirms the design.
- U2 Positioning: portfolio + quant analytics. The AI layer (stage 6) only interprets structured quant output.
- U3 Stack: same as V1 (FastAPI, PostgreSQL/SQLAlchemy, React + TypeScript + Vite), Python 3.11+ declared.
- U4 Stage 1 scope: NSE/BSE equities and ETFs, INR only.
- U5 Quant split by risk: Quant V1 = market data, returns, volatility, drawdown, risk metrics on the user's own
  portfolio; Quant V2 = pairs, cointegration, strategy, sizing; Backtesting = execution, backtester loop,
  evaluation, walk-forward.
- U6 Tradebook import in stage 1 only; sealed ledger, bias cost, skill-vs-luck, replay report go to stage 7.
- U7 Single user, local first; `user_id` scoping and isolation tests stay in the model. No deadline assumed.
- U8 Constitution carried forward, revised; the V1 -> V2 diff was approved: 8 laws, V1 Laws 3 and 7 dropped, no
  retired numbers kept, V1 Law 8 unchanged (V2 Law 6). Mapping V1 -> V2: 1->1, 2->2, 4->3, 5->4, 6->5, 8->6, 9->7, 10->8.
- U9 (review approvals): trades append-only with `supersedes_trade_id` and `recorded_at`; dedupe on `broker_trade_id`
  via a partial unique index on original rows; Decimal-everywhere with float only in statistics; top-level
  `app/quant/`; stdlib-only `app/domain/` for shared enums and `Instrument`.
- U10 (Feature 002 owner decisions, 2026-10-11; details in `docs/plans/002a-decisions.md`): ISIN is the holding identity
  (NSE and BSE merge; legacy NULL-ISIN separate); dedupe key includes exchange; imports store zero fees with
  `charges_provided=false`; nullable name/type/session for imports; IST timestamps; 2 MiB / 5,000-row limits; per-user
  `NOWAIT` lock; oversell quarantine per ISIN; no estimated opening balances. Refines U9 dedupe and `(symbol, exchange)` identity.
- U11 (Feature 003 owner decisions, 2026-10-12; `docs/plans/003-market-data-portfolio-summary.md`): httpx-direct Yahoo
  adapter; ISIN holdings quote NSE then BSE; summary adds market value and unrealized P&L (not in FR-8); quotes fetched
  per request, no cache or persistence, stale after 7 days; valuation is current-only (`as_of` rejected).

## Preserved (proposed-inherited)

| # | Item | V1 source | Notes |
| --- | --- | --- | --- |
| P1 | AI optional, provider-neutral, behind an orchestration port; never authoritative for financial calculations | constitution.md Law 9; ai-provider-architecture.md | Matches the V2 core principle |
| P2 | Quant package pure and framework-free; library code isolated to one adapter | quant-domain.md "Mathematical boundary rule"; ADR 003 | Enforce with an import-boundary test |
| P3 | Point-in-time safety is structural; `MarketSeries.truncated_to(T)` is the only narrowing | market-data.md; quant-domain.md | Each layer gets a "future data cannot change the result" test |
| P4 | Bar timestamp = close, UTC, tz-aware; fill at next bar open; settle-then-mark-then-decide loop | ADR 002; backtesting.md | Applies from the Backtesting stage |
| P5 | Invalid bars rejected at construction; inner-join alignment; explicit `adjusted` flag; `DataProvenance` fingerprint | market-data.md; pairs-research.md | Fingerprint detects drift, does not prevent it |
| P6 | Decimal for money; one documented Decimal-to-float crossing for statistics; undefined = `None`/`Unavailable(reason)` | features.md; performance-evaluation.md | See C1 for the sizing/execution caveat |
| P7 | Research accounting separate from the real user ledger | research-accounting.md; ADR 002 | Backtests never read or write live tables |
| P8 | Signal, target position, order, fill, position as distinct steps; Strategy, PositionSizer, ExecutionModel swappable | quant-domain.md | Quant V2 and Backtesting stages |
| P9 | Evaluation read-only over a finished result; sample stdev (ddof=1); explicit `periods_per_year`; risk-free and MAR separate | performance-evaluation.md; ADR 008 | |
| P10 | A pairs decision is one atomic record | ADR 001 | Schema never designed in V1 |
| P11 | Observations are deterministic, factual review triggers; never BUY/SELL or predictions; exact Decimal comparisons | ADR 009 | Fits Analytics UI stage |
| P12 | Honesty rules: no profitability claims; thresholds are research parameters; record trial counts; correlation is not cointegration | pairs-research.md; ADR 004, 010 | |
| P13 | Layering router -> service -> repository -> model; isolation tests at repository, service and route level | CLAUDE.md (V1) | |
| P14 | Process: one ADR per decision, docs under 200 lines, one owner per file, never push | CLAUDE.md (V1); decisions.md | |

## Changed (candidate changes, each needs approval in design)

| # | V1 behaviour | V1 source | V2 direction |
| --- | --- | --- | --- |
| C1 | Sizing and execution notionals are `float`; the exit-residue bug came from float/Decimal mixing | ADR 007 correction 3; backtesting.md | Decimal for all money and quantity including sizing and execution; float only in statistics; exact full exit (design, U9) |
| C2 | Quant built before persistence and UI | milestones.md; implementation-log.md | V2 order is accounting, Quant V1, UI, Quant V2, Backtesting, AI, research |
| C3 | Twin makes independent BUY/SELL/HOLD decisions (Laws 3, 4, 7) | constitution.md; PRD.md | Dropped from v1 scope under U2; any later twin is policy-driven and AI only narrates |
| C4 | Expanding-window refit every bar (O(n^2)); hedge ratio never frozen | backtesting.md; ADR 007, 010 | Revisit at Backtesting stage; ADR 010 open questions stay open |
| C5 | Dev-only `X-User-Id` fallback auth | CLAUDE.md (V1); current-state.md | Single user for now (U7); real auth is a later decision |
| C6 | Yahoo only, NSE assumed, uncached `Ticker.info` sector calls | market-data.md; progress 2026-10-08 | Provider abstraction kept; BSE/NSE handling and caching decided in design |
| C7 | Required `postgres_*` settings block test collection; Python version undeclared | progress 2026-10-07, 2026-10-08 | Tests run without a database config; Python 3.11+ declared from commit one |
| C8 | No scope gate; sector breakdown built off-plan while M0 was blocked | progress 2026-10-08 | Each feature needs a plan file before code |
| C9 | Quant imported `app.models.enums` as a documented exception | research-accounting.md | Shared types move to stdlib-only `app/domain/`; quant imports no ORM or framework (U9) |
| C10 | Mutable `Trade` rows (`updated_at`), no correction policy | API.md | Append-only with supersede link, `recorded_at`, `broker_trade_id` dedupe (U9) |

## Deferred
- Hash-chain sealed decision ledger, bias cost in rupees, skill-vs-luck, replay report UI (V1 build-plan M3-M6): stage 7.
- Walk-forward out-of-sample evaluation (ADR 010, proposed only): Backtesting stage.
- Cointegration gating and point-in-time pair selection: Quant V2 / Backtesting.
- Azure deployment and infrastructure-as-code (V1 M7a/M7b): decided after stage 3.

## Dropped from v1 scope
- Twin portfolio, twin replay, Astra twin chat (V1 M2 and AI twin laws).
- Multi-asset types beyond equities and ETFs (V1 enums include funds, bonds, gold, futures, options).
- Real multi-user auth.

## Not carried over (V1 defects or stale docs)
- Backtests with more than one trade produced before V1's M13-0 fix are contaminated; no V1 result is a V2 baseline.
- V1 `architecture.md`, `roadmap.md`, `milestones.md`, `API.md` are stale (July 2026); not used as sources of fact.
