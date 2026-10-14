# Feature 007: Luck Test (plan)

Contract: `docs/specs/007-luck-test.md` (it wins). Sprint mode: one review at the end. No Git by the agent.
Package `backend/app/quant/luck_test/`; tests `backend/tests/test_luck_test_*.py`; builders `tests/luck_helpers.py`.

## 1. Modules (public names)
- `errors.py`: `LuckInputError`, `Unavailable`, `UnavailableReason`, `ExclusionReason`, `GATE_REASONS` (local; no sibling import).
- `types.py`: `TripInput`, `Candidate`, `Membership`, `LuckParameters`, `AlternativePick`, `CandidateExclusion`, `TripLuck`,
  `BaselineSummary`, `LuckResult` (`TripLuck.evaluated`, per-trip `actual_return_basis`, `known_corporate_action_listing_count`,
  top-level `unavailable`), constants (`FORMULA_VERSION="luck-v1"`, `RNG_VERSION="luck-rng-v1"`, `SCHEMA_VERSION=1`).
- `numeric_boundary.py`: `to_float(Decimal) -> float` (the only `float(` call), `CALC` 60-digit half-even context.
- `rng.py`: `SplitMix64`, `derive_seed(seed, formula, trip_id, stream)`, `randbelow`, `sample_without_replacement`,
  `simplex_weights(rng, k) -> tuple[Decimal, ...]`.
- `features.py`: `PreTradeView` (last 61 closes before `d`, nothing later), `momentum`, `volatility`, `pool_stats`/`PoolStats`
  (candidate-pool z-scores), `rank_candidates` (distance, symbol, exchange, ISIN).
- `portfolios.py`: `alt_portfolio_returns`, `nifty_portfolio_returns` (Decimal returns), `compare` (beaten, ties, mean).
- `bootstrap.py`: `excess_and_percentile`, `bootstrap_mean_interval` (fsum, rank rule from spec section 7), `position`.
- `fingerprint.py`: `input_fingerprint(...)` reusing `canonical_decimal`, `iso_utc` from `app.quant.market_data.fingerprint`.
- `analysis.py`: `analyze_luck(..., parameters, *, corporate_action_reviewed=None)`; `None` = undeclared => Unavailable result.

## 2. Allowed imports
stdlib (`hashlib`, `json`, `math`, `bisect`, `decimal`, `datetime`...; NOT `random`, `secrets`, `time`), `app.domain`,
`app.quant.market_data` (`MarketSeries`, `canonical_decimal`, `iso_utc`, `local_date`), sibling modules by RELATIVE import.
Edit `tests/test_import_boundaries.py:46` additively: `("backtest", "bias_cost", "luck_test")`. No 006/005 import.

## 3. Determinism
Everything sorted: trips by (open, close, trip_id), candidates by ISIN, picks by rank. No dict/hash/set-order reliance
(sets sorted before use). `as_of` is an input. Per-trip sub-streams (spec section 6) make results order-independent.

## 4. Steps (tests first per step; focused tests, then `.venv/Scripts/python.exe -m pytest -q` from `backend/`)
1. Errors, types, `numeric_boundary`, boundary-test allowlist edit.   2. `rng.py` with known-answer vectors.
3. `features.py` + leakage tests.   4. `portfolios.py`.   5. `bootstrap.py`.   6. `fingerprint.py`, `analysis.py`.
7. Docs: `docs/specs/README.md` row; spec "as built" notes; one final review of the whole diff (sprint mode).
Commit is the owner's (Git is managed by the owner); I stop with the suite green and the diff summarised.

## 5. Tests (each tagged with a spec section)
`test_luck_test_types.py` (contracts, frozen, validation, boundary/float/clock/random AST scans),
`test_luck_test_rng.py` (vectors, rejection sampling, simplex, sampling), `test_luck_test_selection.py` (leakage,
ties, eligibility, lost alternatives), `test_luck_test_analysis.py` (statistics, bootstrap, seed, isolation,
Unavailable matrix, fingerprints). Synthetic `ZZ` symbols, no network, no DB.

## 6. Limits to record
Close is split-adjusted but ledger is raw (listed corporate actions excluded, none detected); trips overlap and correlate;
universe/membership come from the caller; baseline A clusters near its equal-weight mean; no multiple-testing correction;
fees excluded from the actual return; same-day entry bar is used for selection availability (not its price).
Cost is O(trips x universe x 61 bars) per run and exclusions are listed per trip; acceptable at the caps (2,000 trips).
STATUS: steps 1-7 implemented; final review done 2026-10-14. Policy: corporate-action coverage is a prerequisite (undeclared =>
`Unavailable(CORPORATE_ACTION_COVERAGE_UNDECLARED)`). Audit fixes: common gate reason in summaries, `evaluated` per trip (null,
not []/0, when false), trip-level fees-excluded basis, top-level `unavailable`; `known_corporate_action_listing_count` = size of
the supplied known-actions set (relevant or not), not an exclusion count.

## 7. Out of scope
Service, API, persistence, cache, UI, 006 changes, Nifty membership sourcing, corporate-action detection, block bootstrap.
