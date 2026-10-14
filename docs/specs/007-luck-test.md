# Feature 007: Luck Test
Status: implemented, reviewed, contract audit fixes applied 2026-10-14. Formula `luck-v1` is a heuristic comparison, not proof of skill or causation.
Plan: `docs/plans/007-luck-test.md`. Package: `backend/app/quant/luck_test/`. Historical and observational only.
## 1. Objective
For each closed round trip, compare its holding-period return with (A) random-weight portfolios of up to 10 stocks that were
similar before the trade and (B) random 10-stock Nifty 50 portfolios, then bootstrap the mean excess return across trips.
Out of scope: backtesting, strategies, optimisation, brokers, execution, persistence, API, UI, caching, new dependencies.
## 2. Inputs (all caller-supplied; the repository cannot yet produce items 2-4)
- `TripInput(trip_id, instrument, isin|None, open_session, close_session, cost_inr, proceeds_inr)`: a fully closed round trip
  (006 definition), cost = sum(buy qty*price), proceeds = sum(sell qty*price), Decimal ledger prices, FEES EXCLUDED.
- `series: Mapping[Instrument, MarketSeries]` (INR); `universe: tuple[Candidate(instrument, isin)]`, one listing per ISIN.
- `nifty50: tuple[Membership(isin, from_date, to_date|None)]`: dated half-open [from, to) intervals, read at each trip's own
  decision date. A current constituent list is not historically valid and is never inferred; no interval on `d` => `NO_MEMBERSHIP`.
- Corporate-action coverage is a PREREQUISITE. `corporate_action_reviewed` = the caller's declaration of the listings whose
  actions it reviewed; it is a declaration, not proof of completeness, and its accuracy stays the caller's responsibility.
  Omitted (`None`) => the whole result is `Unavailable(CORPORATE_ACTION_COVERAGE_UNDECLARED)`: trips are listed, none is
  evaluated, nothing is assumed clean. Declared (even empty): `corporate_action_listings` (KNOWN actions, effect unadjusted)
  are excluded as `CORPORATE_ACTION`; any listing outside the declaration as `CORPORATE_ACTION_UNKNOWN`. Nothing is detected.
  `known_corporate_action_listing_count` = number of entries in the supplied known-actions set, relevant or not (no exclusion count).
- `LuckParameters`: `seed` (int 0..2^64-1), `as_of` (aware UTC, never the clock), `formula_version`, section 3 values.
## 3. Decisions (owner 2026-10-14)
- Unit: one closed round trip, equal weight per trip. Decision date `d` = `open_session`; exit `j` = `close_session`.
- Actual `Ra = (proceeds - cost) / cost` from ledger prices, fees excluded (stated in the output). Alternative `R = close[j] /
  close[d] - 1` on split-adjusted `close` (`adjusted_close` never read, dividends excluded). Fills vs closes is a limitation.
- 500 portfolios per baseline. A: 5..10 alternatives, random weights. B: exactly 10 stocks without replacement from the
  eligible Nifty 50 pool, random weights. Bootstrap: unit = trip, mean excess return, 95% percentile, 10,000 replicates, >= 10 trips.
- Lost alternative (no bar on `j`): dropped, counted, `survivorship_flag` set; never refilled or valued.
- Similarity (approved): at the last bar `p` before `d`, momentum `m = close[p]/close[p-20] - 1`; volatility `v` = SAMPLE
  standard deviation (n-1) of the 60 daily simple returns ending at `p`. Each feature is z-scored over the ELIGIBLE CANDIDATE
  POOL (population sd, n); the traded stock is standardised with the pool's mean and sd and is not part of them. A zero-sd
  feature gets z = 0 for everyone and is listed in `zero_variance_features`. Distance = squared Euclidean on (z_m, z_v).
## 4. Eligibility
- Trip (both baselines): coverage declared; listing not a known or unreviewed corporate-action listing; series exists with bars on `d` and `j`;
  `close_session` local date < local date of `as_of`; unique `trip_id`. Baseline A also needs 61 bars before `d`.
- Candidate: not the traded stock (ISIN, or instrument if the trip has no ISIN); series; corporate-action clear; 61 bars before
  `d`; a bar on `d`. A bar on `j` is checked after selection. Every exclusion is recorded with a reason, never filled with 0.
- Duplicate ISIN or instrument in `universe`, duplicate `trip_id`, naive time, non-INR, malformed membership: `LuckInputError`.
- Pre-trade rule: selection reads only closes with `session_date < d` (`PreTradeView` holds nothing later). `d`/`j` closes are
  outcome prices and `as_of` bounds `j`. Overlapping trips are evaluated independently (see section 7).
## 5. Selection
Rank eligible candidates by (distance, symbol, exchange, ISIN) ascending (canonical instrument identifier breaks ties); take the
first 10. Fewer than 5 with an exit bar => baseline A `Unavailable` for the trip. Selection never sees `j`.
## 6. Randomness (`luck-rng-v1`)
- SplitMix64. Sub-stream seed = first 8 bytes (big-endian) of SHA-256 of the JSON array `[seed, formula_version, trip_id,
  stream]`, stream in {`alt`, `nifty`, `boot_alt`, `boot_nifty`} (bootstrap trip_id ""): a trip's draws ignore other trips.
- `randbelow(n)` by rejection sampling. Sampling without replacement = partial Fisher-Yates over an ISIN-sorted pool.
- Weights: k-1 integer cuts in [0, 2^32], sorted; `w_i = gap_i / 2^32` as exact Decimal (uniform on the simplex; sums to 1).
- Portfolio return = sum(w_i * R_i) in Decimal (60-digit half-even). No `random`, `secrets`, `log`, or clock.
## 7. Statistics
Per trip and baseline: `excess = Ra - mean(P)`, `percentile = (beaten + ties/2) / count` (exact Decimal comparisons). Decimal ->
float only in `numeric_boundary.to_float`; floats are statistics only. Summary over available trips: `math.fsum` means; bootstrap
draws n trips with replacement per replicate, sorts the means, interval = elements `ceil(B*a/2)-1`, `ceil(B*(1-a/2))-1`.
Interpretation is a position of the interval against 0, never "skill". Trips are resampled independently although holding
periods overlap, so the interval can be optimistic; no multiple-testing adjustment (`limitations` in every result).
## 8. Unavailable (never zero, never estimated)
Gate reasons (trip NOT evaluated, no selection or draw): `CORPORATE_ACTION_COVERAGE_UNDECLARED` (also the result's),
`CORPORATE_ACTION`, `CORPORATE_ACTION_UNKNOWN`, `NO_TRIP_SERIES`, `NOT_CLOSED_AT_AS_OF`, `MISSING_BAR`. Outcome reasons (trip
evaluated): `INSUFFICIENT_HISTORY`, `INSUFFICIENT_ALTERNATIVES`, `NIFTY_POOL_TOO_SMALL`, `NO_MEMBERSHIP`. A valid zero is a number.
Summary, nothing usable: if every trip carries the SAME reason that reason is both `mean_unavailable` and `ci_unavailable`;
mixed or no trips: means `NO_AVAILABLE_TRIPS`, interval `INSUFFICIENT_TRIPS`. 1-9 usable trips: interval `INSUFFICIENT_TRIPS`, means kept.
## 9. Output and provenance
Frozen, `schema_version` 1: versions, `as_of`, parameters, `seed`, return bases, coverage, `limitations`, input fingerprint
(every input and parameter above, series fingerprints; order-independent SHA-256), trips sorted by (open, close, id), summaries.
`to_dict()`: `schema_version`, `as_of`, top-level `unavailable` (non-null = the whole analysis is unavailable; mirrored in
`provenance`), `provenance`, `inputs`, `values`. Each trip: `evaluated`, `actual_return` with `actual_return_basis` =
`LEDGER_PRICES_FEES_EXCLUDED`. A not-evaluated trip serialises `picks`, `exclusions`, `zero_variance_features`,
`lost_alternative_count`, `survivorship_flag` and outcome counts as null, never [] or 0; summaries add `trips_evaluated`.
## 10. Acceptance tests
1. Leakage: bars on or after `d` cannot change features or selection; bars after `j` change no result.
2. Ties: equal distances rank by symbol, exchange, ISIN; input order never matters. Zero-variance feature handled.
3. Seed: same seed => identical result; other seed differs; SplitMix64 vectors; other trips never change a trip's draws.
4. Portfolios: weights sum to exactly 1; no repeated stock; sizes 5..10 (A) and 10 (B).
5. Insufficient: 4 alternatives, 9 Nifty members, 9 trips, no membership, 0 trips give the named `Unavailable`.
6. Missing data, duplicates, corporate actions: excluded or rejected with a recorded reason. Undeclared coverage, an empty
   declaration and a known action inside the declaration give three distinct outcomes; gated trips are `evaluated` false.
7. Zero vs unavailable; Decimal-to-float only in `to_float`; no float literal, `random`, clock; import boundary; fingerprints.
