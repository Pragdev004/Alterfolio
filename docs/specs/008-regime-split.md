# Feature 008: Regime Split

Status: implemented 2026-10-14, awaiting owner review (not committed). Formula `regime-v1` is a heuristic grouping.
Plan: `docs/plans/008-regime-split.md`. Package (proposed): `backend/app/quant/regime_split/`. Historical and observational only.

## 1. Objective
Label each closed round trip with the volatility regime of its own listing before it opened, then report the Feature 007 luck
analysis and the Feature 006 bias-cost analysis separately per regime. No BUY/SELL wording. Out of scope: fitted or Markov
models, statsmodels, any new dependency, backtesting, API, UI, persistence, caching, services, edits to Features 006/007.

## 2. Evidence
- `CLAUDE.md:145` "008 regime split"; owner decisions 2026-10-14 (per-regime 006+007, rule-based volatility, own listing,
  expanding 33rd/67th percentiles, 120 observations, 10-trip minimum). Obsidian was unreachable.
- 006: `bias_cost/validation.py:51 validate_inputs` (raises on duplicate `trade_id`), `cost_basis.py:80 fold_positions` ->
  `RoundTrip(instrument, open_session, close_session, trades)` (`:36`). A trip opens only on a BUY at zero quantity and every
  trade joins one open state, so each trade is in at most one trip and `trades[0]` is its opening BUY. Undeclared interfaces.
- 007: `analysis.py:272 analyze_luck`, `types.py:100 TripInput`, `features.py:73 volatility`. `trip_id` and `LedgerTrade.trade_id`
  share one identifier rule (non-empty, no whitespace, <= 128): a ledger id is a valid trip id.

## 3. Inputs (caller-supplied; aware-UTC `as_of`, no clock)
`LedgerTrade`s, `series`, `BiasParameters`, `LuckParameters`, universe, Nifty 50 membership, `corporate_action_listings`,
`corporate_action_reviewed` (as in 006/007), `RegimeParameters` (`formula_version`, `volatility_window`=60, percentiles 33/67,
`min_calibration`=120, `min_trips_per_regime`=10).

## 4. Round trips and identity (one-to-one, no matching on dates)
Run `validate_inputs`, then `fold_positions` unless a listing has trades but no series (as `analyze_biases` does). Open
positions and pre-window sells belong to no trip; 006's exclusions are passed through. For each `RoundTrip`:
- `trip_id` = `trades[0].trade_id`. Same-day re-entries on one listing have different opening buys, hence different ids.
- `TripInput`: instrument; `open_session`/`close_session` from the round trip; cost = sum(buy qty*price), proceeds = sum(sell
  qty*price), exact with 006's `CALC_CONTEXT`; fees excluded (007 definition).
- Structural checks, failing with `RegimeInputError` (006 changed): `trades[0]` BUY, `trades[-1]` SELL, one listing, buy qty
  equals sell qty, `open <= close`, `trip_id` unique, no trade id in two trips. `TripInput` rejecting a value is also an error.
- `isin`: every trade None -> None; every trade the same value -> it; mixed None/value or several values -> trip excluded as
  `AMBIGUOUS_ISIN`, listed, in no regime, never guessed.

## 5. Regime label (own listing, point-in-time)
- `d` = `open_session`. `B` = bars with `session_date < d`; `p` = bar index `B-1`. Nothing on or after `d` is read.
- `v(q)` = 007 volatility: SAMPLE sd (n-1) of the 60 simple returns of the 61 closes ending at bar `q` (split-adjusted `close`,
  series bars only, gaps never filled). Valid iff `q >= 60`; positive closes; finite float. sd = 0 is valid. A value that
  cannot be computed finite is an error, never skipped.
- `B < 61`: `INSUFFICIENT_HISTORY`. Calibration pool = `v(q)` for `q` in [60, p-1] of the same listing only, size `n = B-61`;
  `v(p)` is excluded. `n < 120` (`B < 181`): `INSUFFICIENT_CALIBRATION`. Expanding window; no warm start, defaults or later data.
- Nearest rank: sort ascending, `P_k` = value at rank `ceil(k*n/100)` (integer arithmetic, rank 1 smallest), k = 33, 67.
- `LOW` if `v(p) <= P33`; `HIGH` if `v(p) >= P67`; else `NORMAL`. `P33 == P67`: `Unavailable(DEGENERATE_THRESHOLDS)`.
- No series or bar on `d`: `NO_TRIP_SERIES`, `MISSING_BAR`. Unclassified trips are listed with their reason.

## 6. Per-regime results and minimum sample
- Partition: LOW, NORMAL, HIGH or unclassified/excluded; counts sum to the round-trip count.
- 007: `analyze_luck` on the regime's `TripInput`s, unchanged `LuckParameters` (same seed).
- 006: `analyze_biases` on the ledger trades of the regime's round trips; formulas and reasons unchanged. Pooled parts (paper
  positions, chasing baseline, session counts) cover that subset only; per-trip P&L is unchanged (cost resets at flat).
- `min_trips_per_regime` (10 classified trips) governs regime-level aggregates only: 007 summaries and every 006 result and
  profile. Below it: `Unavailable(INSUFFICIENT_TRIPS_IN_REGIME)`; labels, thresholds, counts, ids and exclusions stay. At or
  above it 007/006 apply their own gates. Separate from the bar counts in section 5.

## 7. Output, determinism, limitations
Frozen, `schema_version` 1; `to_dict()`: `schema_version`, `as_of`, `unavailable`, `provenance`, `inputs`, `values`. Order-independent
SHA-256 fingerprint over inputs, parameters and series fingerprints. Float only for `v`; money stays Decimal; no clock or `random`.
Limitations: overlapping windows make the pool autocorrelated; regimes are relative to each stock's own history; small regimes
are Unavailable; no multiple-testing adjustment.

## 8. Contract test (narrow, `tests/test_regime_split_contract.py`)
Pins only what 008 uses: signatures of `validate_inputs`, `fold_positions`, `analyze_biases`, `analyze_luck`; fields of
`RoundTrip`, `LedgerTrade`, `TripInput`; and a fixture: same-day re-entry gives two trips with distinct first ids, each trade in
at most one trip, first BUY/last SELL, a trip's `gross_pnl` equal when folded alone or with all trades.

## 9. Acceptance tests and confirmations
Percentile ranks, edges, degenerate; 60/61 closes; n 119/120 (B 180/181); leakage; ISIN cases; partition; below/at 10; unchanged
006/007; determinism; boundary scans. Confirm: 10-trip gate wording (section 6) and that 008 consumes 006 internals under section 8.
