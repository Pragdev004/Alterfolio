# Feature 006: Bias Cost & Behaviour Profile (plan)

Contract: `docs/specs/006-bias-cost-behaviour-profile.md` (it wins). Sprint mode: one review at the end of the feature.
Package `backend/app/quant/bias_cost/`; tests `backend/tests/test_bias_cost_*.py`.

## 1. Modules (public signatures, types only)
- `errors.py`: `BiasInputError`, `Unavailable` (local; no `quant/backtest` import, decision D6 option (a)). Done.
- `types.py`: frozen contracts. Extended: `BiasParameters` (+ defaulted forward/threshold fields), `BiasMetric` (+ gross cost,
  `fees_known`, `fee_status`, `unknown_fee_trade_count`, `details`, `listings`), `FeeStatus`, `ListingProvenance`.
- `presentation.py`: `present_inr(value) -> Decimal` (the only rounding; half-even, 6 places).
- `context.py`: `CALC_CONTEXT` (60 digits, half-even, no Inexact trap) for divisions only.
- `validation.py`: `validate_inputs(trades, series, parameters, corporate_action_listings) -> ValidatedBiasInputs`.
- `cost_basis.py`: `fold_positions(inputs) -> FoldResult` (sells with gross P&L, round trips, end-of-day positions).
- `market_context.py`: `SeriesIndex` (bar index, close at/before a session, never a later bar).
- `calculations.py`: `calculate_disposition`, `calculate_chasing`, `calculate_overtrading` -> `BiasResult`.
- `profile.py`: `classify_behaviour(facts, parameters) -> BehaviourProfile | Unavailable`.
- `fingerprint.py`: `fingerprint_payload(kind, parts) -> str` (SHA-256 of canonical JSON; reuses `canonical_decimal`, `iso_utc`).
- `analysis.py`: `analyze_biases(trades, series, parameters, corporate_action_listings=frozenset()) -> BiasAnalysisResult`.

## 2. Allowed imports (checked against `tests/test_import_boundaries.py`)
stdlib, `app.domain`, sibling modules by RELATIVE import. `validation`, `market_context`, `calculations`, `fingerprint`,
`analysis` also use `app.quant.market_data` (`MarketSeries`, `canonical_decimal`, `iso_utc`): the quant allowlist in
`test_import_boundaries.py` gains `bias_cost` beside `backtest` (additive). No `quant/backtest`, no float, no clock, no RNG.

## 3. Errors and Unavailable (spec section)
Input defects raise `BiasInputError` (5). Missing series for a TRADED listing blocks all metrics and the profile (owner:
strict completeness, no partial results); an untraded listing's series is ignored. Missing series, no winners, no non-chase buys, undefined PGR/PLR, <10 round trips
are `Unavailable` (3, 4). Excluded listings/sells are recorded in exclusions (5).

H rule (owner, final): observation unit = closed winning round trips, each once (not partial sells; PGR/PLR use sell days). Sorted integer holding sessions, odd => middle, even => lower middle, never averaged.

## 4. Determinism
No seeds exist. Sort by (UTC time, trade id), tie => error. Sessions come from series bar indexes. Per-metric fingerprint
covers only that metric's trades, series fingerprints, parameters and `bias-v1`; the analysis fingerprint covers all of them.

## 5. Steps (tests first; focused then full suite)
1. Contract extensions and `context.py`. 2. Validation. 3. Cost basis fold. 4. Series index.
5. Disposition. 6. Chasing. 7. Overtrading. 8. Profile. 9. Fingerprints and `analyze_biases`.
10. Boundary test edit and the single final review. STATUS: steps 1-10 implemented; tests written after the code.

## 6. Test files (each tagged with a spec section)
`test_bias_cost_types.py` (contracts, boundary scans), `test_bias_cost_calculations.py` (fold and the three formulas),
`test_bias_cost_analysis.py` (archetype, orchestration, listings, fingerprints); builders in `tests/bias_helpers.py`.

## 7. Recorded limitations
Close is split-adjusted and ledger price is raw (known-corporate-action listings are excluded, none is detected). No
calendar: session counts are bar counts, so data gaps shorten them. Overlapping chase windows are not de-duplicated.
Overtrading is one-sided by the owner's formula. NSE and BSE listings of one ISIN are separate positions here, so a sale on
a different listing than the purchase is an oversell or a pre-window sell.
