# Feature 005: Backtesting Foundation (implementation specification)

**Status: PROPOSED, awaiting implementation review.** This is the implementation contract for Feature 005. It is not an
as-built spec yet; it becomes one when the code is delivered. The plan (`docs/plans/005-backtesting-foundation.md`)
holds the reasoning, risks and decisions; where they differ, report it to the owner rather than choosing.
**Baseline:** `e7010bc` (Feature 004). **Scope:** pure, deterministic, point-in-time daily-bar simulation.

## 1. Objective and non-goals
Build a strategy-agnostic backtesting engine that consumes pre-fetched `MarketSeries`, a `BacktestConfig` and a
`Strategy`. It returns a frozen, versioned result: equity curve, orders, fills, rejections, unavailable decisions and
input provenance.

Do not implement: APIs, persistence, database models, caching, AI, concrete strategies, sizing algorithms, performance
metrics, optimization, walk-forward testing, benchmarks, costs, taxes, slippage, dividends, short selling, leverage or
fractional shares.

## 2. Architecture
Package `backend/app/quant/backtest/`:
- `config.py`: `BacktestConfig`, `StrategyIdentity`, `BacktestInputError`, `Unavailable`.
- `portfolio.py`: cash, positions, fills, valuation.
- `calendar.py`: input validation, calendar alignment, point-in-time views.
- `execution.py`: orders, fills, rejections, execution protocol.
- `engine.py`: strategy protocol and simulation loop.
- `result.py`: immutable result, serialization, fingerprint.

Quant imports may use the standard library, `app.domain`, and `app.quant.market_data`. Never import providers,
services, APIs, database frameworks, ORM models or AI modules. Reuse Feature 004 types and utilities (`MarketSeries`,
`MarketBar`, `truncated_to`, `local_date`, `canonical_decimal`, `iso_utc`); do not duplicate them. The engine must not
fetch data, read a clock, persist state or use randomness.

## 3. Configuration and strategy contract
`BacktestConfig` contains: inclusive `start_date` and `end_date`; positive `initial_cash` (`Decimal`, strictly below
`MAX_AMOUNT`); a `Currency`; an explicit price-basis identifier (`SPLIT_ADJUSTED_OPEN_CLOSE`, the only supported value).
Invalid dates, amounts, currency, price basis or incompatible inputs raise `BacktestInputError`.

Strategy identity is separate from `BacktestConfig`. `StrategyIdentity` holds a stable `strategy_id`, a `version`, and
canonical text `parameters` (sorted by key; ints and Decimals as exact text; floats and bools rejected). Each
`Strategy` exposes its `identity`. The strategy owner MUST change `version` whenever behavior changes; the engine only
records and fingerprints it and cannot verify it.

The `Strategy` protocol accepts an immutable `StrategyView` and returns target share quantities by instrument, or
`Unavailable(reason)`. The view contains the current session date, historical series truncated to that date, cash and
positions. Every mapping exposed to a strategy is read-only (a copied `types.MappingProxyType`); a strategy cannot
reach the full, untruncated input series through the view. The engine copies the mapping a strategy returns before use.
Targets must be non-negative whole shares; negative or fractional targets raise `BacktestInputError`.

## 4. Calendar and historical information
- Validate: non-empty series, unique instrument identities, compatible currencies, matching exchange offsets.
- Calendar = intersection of session dates across all configured instruments within the requested range. Count and
  record every excluded date. Never interpolate or fabricate prices.
- Keep pre-start history visible for strategy warm-up; never trade before `start_date`.
- An empty common calendar returns `Unavailable` with a reason.
- Use `session_date` for all simulation time logic, never provider timestamps.
- Build each view with Feature 004's `truncated_to` (instant = local midnight of D+1 in the exchange offset, derived
  from the date, never a clock) so no bar after the decision date is visible.
- Insufficient history yields `Unavailable(reason)` for that date: positions are unchanged, and previously queued
  orders still settle normally.
- Reject incompatible series or invalid cutoffs explicitly; never silently truncate the requested backtest.

## 5. Timeline and execution
For each common session D, in this order:
1. Execute orders queued after the previous session's close at D's open.
2. Apply fills or rejections to cash and positions.
3. Mark holdings at D's close.
4. Construct the immutable strategy view with information through D only.
5. Obtain target shares or an unavailable decision.
6. Derive orders (target minus current holdings) and queue them for the next common session.

A decision on D's close cannot fill at D's open or close; the earliest fill is the next common session's open. Orders
queued on the final session are recorded `UNFILLED_END_OF_DATA` and never filled beyond the supplied horizon.

## 6. Prices, share units and corporate actions
- Execute at the split-adjusted provider `open`; value at the split-adjusted `close`. Never read `adjusted_close`;
  dividends are excluded.
- Share quantities are units in the same split-adjusted basis as the supplied bars. They are NOT guaranteed historical
  share counts and must not be compared with ledger quantities or holdings. Example: after a later 1:5 split, "10
  shares" here corresponds to 2 shares actually held at the time. INR cash and equity are unaffected by the unit choice.
- Label every result: no transaction costs, taxes, slippage or dividend accounting. Results are gross, price-only
  simulations, not net investor returns. Bonus, rights and other corporate actions are not modelled (open TBD).

## 7. Accounting and execution
Long-only, cash-funded, whole shares.
- Buy debits cash by quantity x execution price; sell credits it.
- Reject an unaffordable buy in full (`INSUFFICIENT_CASH`); reject an oversell in full. Never partially fill, resize or
  clamp. Cash and positions never go negative.
- Same-session sells execute before buys; instruments are processed by `(exchange, symbol)`.
- Record every order's terminal outcome; link every fill to its originating order; record fill date, instrument,
  quantity, price and notional.
- Use existing instrument identity and Decimal rules. All arithmetic uses `EXACT_CONTEXT`; no implicit rounding, no
  binary float. Any value at or above `MAX_AMOUNT` raises `BacktestInputError`.

## 8. Results and reproducibility
Return `BacktestResult` for a completed run, or `Unavailable` when a valid run cannot be performed (empty calendar,
insufficient usable history). Invalid inputs raise `BacktestInputError`.

The result includes: `schema_version=1`; strategy id, version and canonical parameters; requested period and actual
common calendar; equity curve (date, cash, positions value, equity); orders, fills, rejections and unavailable
decisions; final cash and positions; per-series provenance (source, fingerprint, `retrieved_at`, cutoff,
`knowledge_basis`); excluded-date facts; explicit assumptions (costs, slippage, taxes NONE; dividends EXCLUDED; fill
NEXT_SESSION_OPEN; mark CLOSE; shares WHOLE; share_units SPLIT_ADJUSTED).

- `as_of` is deterministic: `as_of = min(series.cutoff for series in inputs)`. The result never reads the wall clock
  and has no run-time field; a later service may stamp one outside the fingerprinted result.
- Result structures and every nested mapping are genuinely immutable: tuples and `MappingProxyType`, never a bare
  `dict`/`list`. `to_dict()` builds fresh containers on each call, so mutating its output cannot change the result.
- Monetary JSON values are canonical Decimal strings. The fingerprint is a hash of canonical, sorted serialization.
- Record the limitation of retrieval-time-restated data: these bars do not prove which prices were known at each
  simulation date (`knowledge_basis` stays `AS_FETCHED_AT_RETRIEVAL`).

## 9. Determinism and temporal correctness
Identical inputs, configuration and a deterministic strategy give identical results and fingerprints. The engine must
not depend on clock time, global mutable state, randomness, hash iteration order or input mapping order.

Required tests:
- Perturb bars after cutoff T: results through T are identical.
- Change D+1's open: D's decision is identical; its fill may change.
- A peeking test strategy never observes a session after its decision date.
- An order decided on D fills no earlier than D+1's open; final-session orders stay unfilled.
- An unavailable decision preserves holdings and does not cancel previously queued orders.
- Repeated runs and permuted input order give equivalent results.
- Exact Decimal accounting matches hand-computed scenarios.
- Missing dates, empty calendars, insufficient history and invalid cutoffs are explicit.
- No `adjusted_close` access in the engine.
- Mutating a view, a strategy-returned mapping, `to_dict()` output or any result mapping never changes a run.
- Strategy version or any parameter change changes the fingerprint; `as_of` equals `min(cutoff)`.
- Import-boundary tests prohibit higher-layer dependencies and float-based monetary calculations.

## 10. Implementation sequence
One step at a time, TDD; stop after each step and wait for explicit approval.
1. Config and errors (`config.py`): types, validation, `Unavailable`.
2. Portfolio: cash/positions, fill application, valuation, invariants.
3. Calendar and views: validation, intersection, dropped dates, temporal truncation.
4. Execution: order/fill/rejection models, next-open execution.
5. Engine: simulation loop and strategy protocol.
6. Result: frozen result, canonical serialization, fingerprint, provenance.
7. Boundaries and docs: purity tests, import-boundary updates, specs index, lineage, `CLAUDE.md`, approved design updates.

Each step reports files changed, tests added, focused and full suite results, deviations and concerns. Do not commit or
push unless explicitly instructed.

## 11. Acceptance and verification
New Markdown stays under 200 lines. Run focused tests and the full backend suite after each step
(`backend/.venv/Scripts/python.exe -m pytest`). Final verification must establish:
- All temporal, execution, accounting, immutability and determinism tests pass.
- Features 001-004 behavior and tests are intact; quant import boundaries are enforced.
- No hidden clock, randomness or float-based monetary path.
- No accidental migration, dependency, generated-file or unrelated changes.
- Documentation states the implemented price basis, share-unit semantics, data limitations and gross-return assumptions.

Do not expand the feature beyond this scope without owner approval.
