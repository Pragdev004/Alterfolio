# Plan 008: Regime Split

Status: implemented (steps 1-7), awaiting owner review. Spec: `docs/specs/008-regime-split.md`.

## Goal
Pure quant package `backend/app/quant/regime_split/`: label each 006 round trip with a point-in-time, own-listing volatility
regime (expanding nearest-rank 33rd/67th percentile of 60-session volatility, 120 prior observations) and report 007 and 006
per regime. No dependency, no statsmodels; Features 006 and 007 are not modified.

## Reuse (read-only)
- 006: `bias_cost/validation.validate_inputs`, `cost_basis.fold_positions`/`RoundTrip`, `analysis.analyze_biases`,
  `context.CALC_CONTEXT`, `types.LedgerTrade`/`BiasParameters`.
- 007: `luck_test/analysis.analyze_luck`, `types.TripInput`/`LuckParameters`, `features.ListingBars`/`volatility`.
- `app/quant/market_data` `MarketSeries`; fixtures `tests/bias_helpers.py`, `tests/luck_helpers.py` (not edited).
These are undeclared interfaces; the contract test (step 3) is the only guard and nothing is promoted to public API.

## Identity contract (spec section 4)
`trip_id` = opening buy `trade_id`; structural checks raise `RegimeInputError`; ambiguous ISIN excludes the trip.

## Steps (one at a time; focused tests, then the full suite)
1. Owner signs off the spec (section 9 confirmations).
2. `errors.py`, `types.py`: `RegimeParameters`, `Regime`, reasons, `TripRegime`, `RegimeResult`, `to_dict`.
3. `tests/test_regime_split_contract.py` first (signatures, fields, same-day re-entry fixture), then `trips.py`: round trips
   via `validate_inputs` + `fold_positions` (mirror the `missing_series` gate), `TripInput` build, ISIN rule, checks.
4. `classify.py`: `v(q)` series per listing (computed once per call), integer nearest rank, label, reasons.
   Tests: ranks, edges, degenerate, 60/61 closes, B 180/181, leakage, current observation excluded.
5. `analysis.py`: partition, per-regime `analyze_luck` and `analyze_biases`, minimum gate, fingerprint.
   Tests: partition, order independence, below/at 10, 006/007 outputs unchanged, determinism.
6. `tests/test_regime_split_boundaries.py`: imports, no float literal/clock/random.
7. One final review; update spec status and `docs/specs/README.md`.

## Verification
From `backend/`: `.venv/Scripts/python.exe -m pytest tests/test_regime_split*.py -q`, then `.venv/Scripts/python.exe -m pytest -q`.
Confirm no file under `quant/bias_cost` or `quant/luck_test` changed.

## Risks
- 006 internals may change; the contract test fails loudly. Subset re-runs shift 006's pooled baselines (documented).
- About 181 bars per listing are needed; shorter histories give Unavailable by design.
