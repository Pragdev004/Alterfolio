# Feature 005: Backtesting Foundation

**Status: PROPOSED (revision 4). Section 9 decisions are resolved EXCEPT the open stage-5 trial-count gate (D7); NOT implemented.**
Authoritative contract: `docs/specs/005-backtesting-foundation.md` (it wins over this plan). Step 1 exists in the working
tree, uncommitted; steps 2-7 are pending. Rev 2: deterministic `as_of`, share units, read-only views, strategy identity.
Rev 3: cutoffs rejected, `Unavailable` semantics, D4/D5/D7/D8. Rev 4: trial-count gate kept OPEN; Step 2 review fixes.

## 1. Objective and non-goals
Objective: a pure, deterministic, point-in-time daily-bar simulation core in `backend/app/quant/backtest/`. Given
pre-fetched `MarketSeries` objects, a config and a `Strategy`, it simulates a long-only cash portfolio and returns a frozen,
versioned result (equity curve, orders, fills, rejections, provenance). It is the "execution + loop" half of roadmap stage 5.

Non-goals (deferred, section 10): performance metrics/evaluation, walk-forward, benchmarks, any concrete strategy,
position sizers, pairs/cointegration, costs/taxes/slippage models, corporate actions, shorting/leverage, fractional
shares, persistence (`BacktestRun`), API routes, services/DB access, caching, AI, frontend.

## 2. Current-state findings (verified in repo, `main` clean at `e7010bc`)
- Reusable as-is: `MarketBar`/`MarketSeries` (`quant/market_data/{bar,series}.py`), `DataProvenance` + fingerprint,
  `MarketSeries.truncated_to(t)` (the only narrowing; keeps `session_date < local_date(t)`), `local_date`
  (`exchange_time.py`), `canonical_decimal`/`iso_utc` (`fingerprint.py`), `Instrument`, `Currency`, `MAX_AMOUNT`,
  `EXACT_CONTEXT` (prec 100, traps Inexact; `domain/numeric.py`), `MarketSeriesService` (fetch side, unchanged).
- Design already fixes: flow `... -> execution -> backtest -> evaluation`; `Strategy`, `PositionSizer`, `ExecutionModel`
  are Protocols and "Backtester owns the loop only" (`design.md`, lineage P8); loop = settle, mark, decide, fill at next
  bar open (lineage P4); backtests never touch live tables (P7); V1 float notionals are a known defect (C1); V1 O(n^2)
  refit is C4; stage-5 gate = "Leakage tests; trial counts recorded".
- Bar facts to respect: timestamp = provider timestamp (often session START), so all time logic keys on `session_date`,
  never on the timestamp. `close` is split-adjusted, `adjusted_close` also dividend-adjusted; series are
  `AS_FETCHED_AT_RETRIEVAL` (restated), so a backtest is NOT "as known then". Short coverage is valid; 005 decides sufficiency.
- No shared `Unavailable` type exists yet (only service-level `SeriesUnavailable`). Quant has no Strategy/sizing yet
  (stage 4 not built), so 005 ships only the Protocol and test-only fixture strategies.
- Doc drift to fix in step 7: `CLAUDE.md` and `docs/specs/README.md` still call 004 "pending commit" (it is `e7010bc`).
- Boundary test gap: `tests/test_import_boundaries.py::test_quant_imports_only_stdlib_and_domain` rejects absolute
  `app.quant.*` imports (market_data passes only by using relative imports). Step 7 allows `app.quant.*` (intra-quant) explicitly.

## 3. Architecture and dependency direction
```
caller/service (later) -> quant.backtest.run_backtest(series, config, strategy) -> BacktestResult | Unavailable
quant/backtest: stdlib + domain + app.quant.market_data (intra-quant). Never providers/services/api/db/models/ai.
```
Boundary: retrieval is outside. `MarketSeriesService` (services layer) fetches; the engine receives immutable
`MarketSeries` and cannot fetch, read a clock, persist or randomize. A later service (feature 006) composes the two.

Modules (each <200 lines, one responsibility): `config.py` (config, errors, `Unavailable`), `portfolio.py` (cash and
positions), `calendar.py` (alignment, views), `execution.py` (orders, fills, `ExecutionModel`), `engine.py` (loop,
`Strategy` Protocol), `result.py` (result, JSON, fingerprint).

## 4. Data flow and time semantics
1. Inputs: 1..N `MarketSeries` (one per instrument), `BacktestConfig`, `Strategy`.
2. Validate (raise `BacktestInputError`): distinct instruments; one currency equal to config; identical
   `exchange_utc_offset`; each series non-empty; naive/invalid values rejected.
3. Calendar = inner join: session dates present in EVERY series, within `[start_date, end_date]`. Dropped dates are
   counted in the result; nothing is filled or interpolated. Empty calendar -> `Unavailable`. History before
   `start_date` stays visible to the strategy (warm-up) but is never traded.
4. For each calendar date D, in this order (lineage P4):
   a. Settle: fill orders queued on the previous date at D's `open` (rule: next session's open).
   b. Mark: equity = cash + sum(qty x D `close`) after fills.
   c. Decide: build the view with `series.truncated_to(instant)` where `instant` = local midnight of D+1 converted to
      UTC (derived from the date and offset, no clock). The view holds bars with `session_date <= D` only, plus an
      immutable portfolio snapshot (cash, positions). The strategy returns targets or `Unavailable(reason)`.
   d. Orders = target minus held, queued for the next calendar date. On the last date they are recorded
      `UNFILLED_END_OF_DATA`, never filled.
5. Information used to decide on D: bars through D's close. Fill price comes from D+1, which the strategy never sees
   while deciding. Fill and mark for D+1 happen before D+1's decision.
6. The view bound never exceeds the series cutoff: D <= `observed_through` guarantees D+1 local midnight <= cutoff, so
   `truncated_to` cannot raise; the engine still treats a raise as `BacktestInputError`.

## 5. Interface sketches
```python
@dataclass(frozen=True)
class BacktestConfig:           # all fields validated in __post_init__
    start_date: date; end_date: date; initial_cash: Decimal    # >0, < MAX_AMOUNT
    currency: Currency; price_basis: str = "SPLIT_ADJUSTED_OPEN_CLOSE"

@dataclass(frozen=True)
class StrategyIdentity:         # recorded verbatim in the result (trial counting, replay)
    strategy_id: str; version: str; parameters: tuple[tuple[str, str], ...]  # sorted by key, canonical text, no float

@dataclass(frozen=True)
class StrategyView:             # read-only: __post_init__ copies into MappingProxyType(dict) / tuples
    as_of: date; series: Mapping[Instrument, MarketSeries]; cash: Decimal; positions: Mapping[Instrument, Decimal]
class Strategy(Protocol):
    identity: StrategyIdentity
    def decide(self, view: StrategyView) -> Mapping[Instrument, Decimal] | Unavailable: ...   # target SHARES (whole, >= 0)
@dataclass(frozen=True)
class Unavailable: reason: str
class ExecutionModel(Protocol):
    def fill(self, order: Order, bar: MarketBar, cash: Decimal) -> Fill | Rejection: ...
class NextOpenExecution: ...    # fill at bar.open, zero cost; the only v1 model
@dataclass(frozen=True)
class BacktestResult: schema_version: int; as_of: datetime; provenance: ...; inputs: ...; values: ...; to_dict(); fingerprint
```
**`as_of` (deterministic):** `as_of = min(series.cutoff for series in inputs)`, i.e. the instant up to which every input
was complete. It comes only from input provenance, never from a clock, so identical inputs give identical `as_of` and
fingerprint. (A re-fetch yields a new `retrieved_at`/cutoff and so a new result fingerprint; that is intended, since the
data fingerprint and provenance are inputs.) No `created_at`/run time field exists; a later service may stamp one
outside the fingerprinted result.

**Immutability:** frozen dataclasses are not enough. Every public type stores tuples, and any mapping is a copied
`types.MappingProxyType` built in `__post_init__` (view, positions, parameters). The engine copies the strategy's
returned mapping before use, so a strategy cannot mutate engine state through a retained reference. `to_dict()` builds
fresh dicts/lists each call, so mutating its output cannot change the result or its fingerprint.

**Strategy identity:** the result's `inputs.strategy` records `strategy_id`, `version`, and canonical `parameters`
(Decimal via `canonical_decimal`, ints, strings, sorted by key; floats rejected). Rule, written in the spec: the strategy
owner MUST change `version` whenever behavior changes; the engine cannot verify this, it only records and fingerprints it.
Two runs with the same id+version+parameters but different results are therefore a detectable owner error, not an
engine ambiguity.
`values`: `equity_curve` [{date, cash, positions_value, equity}], `orders`, `fills`, `rejections`
(`INSUFFICIENT_CASH`, `UNFILLED_END_OF_DATA`), `decisions_unavailable` [{date, reason}], `final_positions`,
`calendar` facts (first/last date, count, dropped_dates). `provenance`: per-series source, fingerprint,
`retrieved_at`, cutoff, `knowledge_basis`; plus `assumptions` {costs: NONE, slippage: NONE, taxes: NONE,
dividends: EXCLUDED, fill: NEXT_SESSION_OPEN, mark: CLOSE, shares: WHOLE, share_units: SPLIT_ADJUSTED}. Result
fingerprint = sha256 of canonical sorted JSON.

**Share units (spec text, required):** provider `open`/`close` are restated for splits into current share units, so
simulated quantities are counts in that same split-adjusted basis. They are NOT the historical share counts a trader
would have held on that date, and must not be compared with ledger quantities or holdings. A 1:5 split after the
simulated date means "10 shares" here corresponds to 2 real shares then. Cash and equity in INR are unaffected by the
unit choice; per-share prices and quantities are. Bonus/rights/dividends are not modelled (open corporate-actions TBD).

## 6. Numeric, execution and failure rules
- Decimal everywhere; no `float` in the package (AST-tested). Arithmetic uses `EXACT_CONTEXT`: exact, never rounded
  (a 15-digit amount x 20-decimal price exceeds `MONEY_CONTEXT`'s 28 digits, so exactness needs the wide context).
  Cash, positions value, equity must stay `< MAX_AMOUNT`, else `BacktestInputError`. No rounding rule invented.
- Portfolio: long-only, cash >= 0 always, whole-share quantities, no shorting, leverage or margin. A buy larger than
  cash is rejected whole (`INSUFFICIENT_CASH`), no partial fill. Same-date order: sells first, then buys, instruments
  sorted by `(exchange, symbol)`, so outcome is order-independent. Negative or fractional targets -> `BacktestInputError`.
- Costs: none in v1, stated in `assumptions` so no result implies net returns.
- Missing/invalid data: bad bars cannot exist (`MarketBar` rejects them); missing dates are dropped by the inner join
  and counted; orders queued on the previous date settle at D's open before D's decision. A strategy lacking history
  returns `Unavailable(reason)`: the engine records the reason, holds positions and creates no new target orders for D.
  Zero is never substituted. Evaluation metrics are not computed, so none can be silently zero.
- Determinism: no clock, randomness, dict-order, or hash-order dependence; input series sorted by instrument key.

## 7. Implementation steps (each independently reviewable; TDD; commit only when asked)
1. **Config and errors** (`config.py`): `BacktestConfig`, `StrategyIdentity`, `BacktestInputError`, `Unavailable`. Tests:
   each invalid field rejected (naive/inverted dates, non-positive or oversize cash, wrong currency type, empty
   id/version, float parameter); parameters sorted and canonical; identity stored immutably.
2. **Portfolio** (`portfolio.py`): immutable cash/positions, `apply_fill`, `mark`. Tests: exact Decimal sums, cash never
   negative, no oversell, amount bound, hand-computed equity.
3. **Calendar and views** (`calendar.py`): validation, inner join with dropped-date counts, `view_at(D)`. Tests: join
   with a missing date in one series; empty calendar; offset mismatch; view never contains `session_date > D`;
   `truncated_to` instant derivation across a non-UTC offset (IST) and a bar timestamped on the previous UTC day.
4. **Execution** (`execution.py`): `Order`, `Fill`, `Rejection`, `ExecutionModel`, `NextOpenExecution`. Tests: fill price
   = that bar's `open`, sells-before-buys, determinism; catches only `InsufficientCash`/`InsufficientPosition` -> `Rejection`.
5. **Engine** (`engine.py`): the loop of section 4, `Strategy` Protocol. Tests with test-only strategies (buy-and-hold,
   rebalance, always-Unavailable): hand-computed 5-bar scenario to the last Decimal digit; last-date order unfilled;
   `Unavailable` holds positions; warm-up history visible but not traded.
6. **Result** (`result.py`): frozen result, `to_dict`, fingerprint, provenance from input series. Tests: JSON round-trip
   uses canonical Decimal text, same inputs -> identical fingerprint, any changed input bar, strategy version or
   parameter -> different fingerprint; `as_of == min(cutoff)`; the module has no clock call; mutating `to_dict()`
   output, the strategy view mappings, or a mapping the strategy returned never changes the result (TypeError / no effect).
7. **Boundaries and docs**: `tests/test_backtest_purity.py` (mirror of `test_market_data_purity.py`: stdlib + domain +
   `app.quant.market_data` only, no float, no clock/random calls); extend `test_import_boundaries.py` for intra-quant
   imports; write `docs/specs/005-*.md`, update `docs/specs/README.md`, `CLAUDE.md` (status, Architecture, Context Map,
   fix 004 drift), `docs/v1-lineage.md` P4 (stage 5 decision), `docs/design.md` if the price-basis choice is approved.

## 8. Point-in-time and leakage tests (stage-5 gate: "leakage tests")
- Perturbation: change every bar with `session_date > T+1` (prices and count); equity curve, orders and fills dated
  `<= T+1` are identical. Change only D+1's bar: the decision made on D is identical, the fill differs.
- Peeking strategy: a fixture that tries `view.series[i].bars[-1]` records the last `session_date` it sees; assert it
  equals D on every date (never D+1). A strategy handed a series cannot widen it (`truncated_to` raises past cutoff).
- Fill timing: an order decided on D fills at D+1 `open`, never D's close/open; the final date's orders never fill.
- Cutoff: a series whose cutoff cannot cover the requested period (before `end_date`+1) is rejected with `BacktestInputError`; the period is never clipped.
- Holiday gap and one instrument missing a date: join drops it and the fill goes to the next common date.
- Run-twice and permuted-input-order equality; no `adjusted_close` read in the engine (AST/behavior test).

## 9. Decisions (D4, D5, D8 RESOLVED; D7 deferral approved but its stage-5 gate is UNRESOLVED; rest as in the spec)
D1 Price basis: fill at `open`, mark at `close`, both split-adjusted, dividends excluded; `adjusted_close` unused
   (mixing open with dividend-adjusted close would be inconsistent). Alternative: adjusted basis, needs a derived open.
D2 Timing: decide on D's close, fill at next common session's open (matches lineage P4; supersedes "bar timestamp = close").
D3 Quantities: whole shares only (the fractional rounding rule is an open TBD); targets are shares, not weights, so no sizer is needed.
D4 RESOLVED: no transaction costs, taxes or slippage in 005; results are labelled gross. A cost model is its own feature.
D5 RESOLVED: inner-join common session dates; excluded dates are counted and reported.
D6 Engine returns `BacktestResult | Unavailable` (mirrors `ResolvedSeries | SeriesUnavailable`); input defects raise `BacktestInputError`.
D7 Persistence (`BacktestRun`) and the trial registry are deferred to 006; 005 records strategy identity and parameters.
   GATE UNRESOLVED: deferring persistence does NOT by itself satisfy the stage-5 gate "trial counts recorded"
   (`design.md`). It stays open until a reviewed design says how trial counts are recorded without building persistence early.
D8 RESOLVED: build the strategy-agnostic engine now; concrete strategies stay out of scope.
D9 Allow intra-quant `app.quant.*` imports in the boundary test (section 2).
D10 `as_of = min(input cutoffs)` and no run timestamp in the result (section 5). Alternative: omit `as_of`.
D11 Strategy `version` is an owner-maintained string, recorded and fingerprinted but not machine-verified.
D12 Spec must state that quantities are split-adjusted-basis units, not historical share counts (section 5).

## 10. Risks, trade-offs, deferred
- Performance: a `truncated_to` per date copies bars and revalidates, O(n^2) (6000 bars cap, lineage C4). Measure in
  step 5; if too slow, add a prefix-view in `quant/market_data` as a separate reviewed change, not inside 005.
- Restated data: results are not "as known then" (`AS_FETCHED_AT_RETRIEVAL`); recorded in provenance, not fixable here.
- Open corporate actions: splits are in provider prices, dividends/bonuses are not modelled; results are labelled.
- Inner join can hide a provider gap; mitigated by the counted drops.
- Deferred: evaluation metrics (the single documented Decimal-to-float crossing, `ddof=1`, explicit `periods_per_year`,
  P9), walk-forward, benchmark choice, cost/slippage/tax models, sizing, service + API + persistence, trial registry,
  corporate actions, fractional shares, shorting.
- `schema_version=1`; the Decimal, dated, gap-free equity curve lets evaluation consume it unchanged.

## 11. Verification gates
Per step: focused pytest, then the full suite from `backend/` with `.venv/Scripts/python.exe -m pytest` (architecture
tests stay green). Final: diff shows only `quant/backtest/`, its tests and the listed docs; no float/clock/random in the
package; Markdown <200 lines; hand-computed scenario matches; no secrets. Live Yahoo/PostgreSQL not needed.
