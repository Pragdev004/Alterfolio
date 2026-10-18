# Spec 013a: Analysis read API
Status: PROPOSED (spec only, awaiting owner review). Precedes any UI work in Feature 013 (`013-frontend.md`).
Reads: `services/portfolio_analysis.py`, `api/routes/{analyst,portfolio,trades,imports}.py`, `api/display.py`,
`schemas/*`, quant result types of 006/007/008. No change to `domain/` or `quant/`.

## 1. Goal
Expose, read-only and per trip / per regime / per bias, what `PortfolioAnalysisService.analyse` already computes, plus the
latest sealed `as_of` and the minimum-trip thresholds, so the UI never calls the analyst to see a number. Expose only what
is already computed: no new statistic, no new formula, no new threshold. Every number is accompanied by a server-formatted
display string; the frontend never formats.

## 2. What exists today (verified in code)
- `analyse(user_id, as_of) -> AnalysisFacts`: flat `facts` (name, value, source, unit), `provenance`, `unavailable`.
  Only the LAST trip's luck fields become facts. Per-trip `TripLuck`, per-trip `TripRegime`, `RegimeBlock`s and per-kind
  `BiasResult`s exist inside the quant results but are discarded after fact emission.
- `_luck()` runs 007 once per distinct alternatives group (Feature 014) and keeps only the group holding the last trip;
  `provenance.luck_alternatives.per_trip` holds `[trip_id, symbol, label]` for every trip.
- `require_sealed(as_of)` raises 422 `as_of_not_sealed` when `as_of >= today (IST)` using the injected clock.
- `display.py`: `format_inr` (2 dp, Indian grouping, half-even), `format_percent`, `display_value(name, value, unit)`;
  Unavailable renders as the word "Unavailable". Used only for analyst text today.
- Thresholds live in parameters: 007 `LuckParameters.min_trips=10`, 008 `RegimeParameters.min_trips_per_regime=10`, 006
  `BiasParameters.min_round_trips=10`.
- Trip identity: content-derived `trip_id` (007 `TripLuck.trip_id`, 008 `TripRegime.trip_id`). Whether the two sets of
  ids match for the same input is verified by test T5; if they differ this spec stops and is revised.

## 3. Required service change (read types only)
`analyse()` also returns a frozen `AnalysisDetail` next to `AnalysisFacts` (new method `analyse_detail`, `analyse` unchanged):
all `TripLuck` of every alternatives group (each tagged with its group label), the full `RegimeResult` (`trips`, `blocks`),
the full `BiasAnalysisResult` (`results`, `profile`, `exclusions`), the thresholds, and the existing provenance. Same single
clock reading, same seeds, same inputs, so detail and facts agree exactly (test T4). Nothing is persisted. No float in any
public JSON: statistic floats are converted once with the existing `_stat` rule (`Decimal(repr(x))`, canonical text).

## 4. The display-string rule (all endpoints the UI uses)
- Every Decimal-valued or ratio-valued field `x` in a response is returned as an object:
  `{"value": "<canonical decimal text>" | null, "display": "<formatted text>" | "Unavailable", "unavailable_reason": null | "<text>"}`.
  `display` comes from `display_value` (INR via `format_inr`, ratios via `format_percent`, notes ` (lower bound)` /
  ` (fees excluded)` kept). A missing value has `value: null`, `display: "Unavailable"`, and a reason. Never 0 or "".
- Prices and quantities: `display` for INR amounts and prices uses `format_inr`; quantity uses the plain canonical decimal
  text (no rounding). The exact `value` is always present too.
- Counts and thresholds: `{"value": "7", "display": "7"}`. Plain JSON integers (row counts, `total_trips`) stay integers.
- Existing endpoints stay backward compatible: for `GET /trades`, `GET /trades/{id}`, `POST /trades*`, `GET
  /portfolio/holdings`, `GET /portfolio/summary` (including `QuoteOut.price`, `market_value`, `unrealized_pnl`, totals) and
  `POST /imports/tradebook`, each existing Decimal field `x` keeps its current string and gains a sibling `x_display`
  (`"Unavailable"` when `x` is null, with `x_unavailable_reason` when a reason exists, e.g. `quote_status`). The summary
  `valuation_status` also gets `valuation_text` ("3 of 5 holdings valued") built server-side.
- One implementation: a `schemas/display.py` helper wrapping `api/display.py`; no second formatter.

## 5. Endpoints (all GET, user from `get_current_user_id`, never from the client)
`as_of` (query, ISO date, optional): omitted = latest sealed. Every response echoes `as_of` and `as_of_defaulted: bool`.
An `as_of` >= today (IST) is 422 `as_of_not_sealed` (existing error). The server never uses today.

`GET /api/analysis/meta`
- `latest_sealed_as_of` = IST date of the injected clock minus one day; `today_ist`; `thresholds`:
  `luck_min_trips`, `regime_min_trips_per_regime`, `bias_min_round_trips` (each with `display`); `alternatives_note`:
  fixed server text "Same-sector or same-universe alternatives, not a prediction." ; `limitations` (007/008 strings).
- Does not touch the ledger or market data; cheap.

`GET /api/analysis/trips?as_of=`
- `summary`: `trip_count`, `trips_evaluated`, per baseline (`ALT`, `NIFTY`): `trips_used`, `mean_excess`,
  `mean_percentile`, `ci_lower`, `ci_upper`, `position`, each with the display rule; `sample`: `{"have": n, "needed": N,
  "text": "(n of N trips needed)"}` (N from the thresholds, n = usable trips) and `enough: bool`.
- `trips[]` sorted by (open, close, id): `trip_id`, `symbol`, `exchange`, `open_session`, `close_session`, `evaluated`,
  `actual_return` (+ basis `LEDGER_PRICES_FEES_EXCLUDED`), `alternatives_label` (from provenance), `alt` and `nifty`
  outcomes (`percentile`, `excess`, `mean_return`, `pool_size`, `lost_count`, `unavailable_reason`), `survivorship_flag`,
  `regime` (label or reason, joined by `trip_id`, `null` plus reason if absent).
- `excluded_listings[]`: symbol, exchange, reason, `trips` count (trips on these listings are counted but have no row,
  because they never reached 007; the response says so).
- `caveats[]`: static-universe/survivorship note, price-proxy note, `late_recorded_row_count` note, fees-excluded note.

`GET /api/analysis/trips/{trip_id}?as_of=`
- The row above plus `picks[]` (rank, symbol, exchange, `return_ratio`; `distance` is not shown as a number), exclusions
  (reason), `zero_variance_features`, `regime` detail (`volatility`, thresholds, `calibration_count`, each with display
  rule). 404 `analysis_trip_not_found` for an id not in this user's analysis (new `LedgerError` subclass, 404).

`GET /api/analysis/regimes?as_of=`
- `round_trip_count`, `unclassified_count`, three blocks LOW / NORMAL / HIGH always present: `trip_ids`, `trip_count`,
  `sample` (`n of N`), luck summary (`ALT` fields as above) or Unavailable+reason, bias costs per kind. Below
  `regime_min_trips_per_regime` the block shows `INSUFFICIENT_TRIPS_IN_REGIME` and the counts, nothing else computed.
- `exclusions[]`, `limitations[]` ("regimes are relative to each stock's own history").

`GET /api/analysis/biases?as_of=`
- Three entries DISPOSITION / CHASING / OVERTRADING: `cost_inr` (display rule, unit `INR` or `INR_LOWER_BOUND`),
  `gross_cost_inr`, `fees_known`, `fee_status`, `unknown_fee_trade_count`, `exclusions`, `details`; `profile`:
  `archetype_id` or Unavailable+reason, `supporting_metrics` (each value via the display rule), `sample`
  (`n of N eligible closed trips`). Wording fields are observational ("review trigger"), never BUY/SELL.

All five: Unavailable inside a successful analysis is HTTP 200 with the marker (never 5xx, never 0). Input rejections
inside an analysis (`BiasInputError`, etc.) appear as `analysis_errors` with a reason, matching `facts.unavailable`.

## 6. Ask endpoint (additive)
`POST /api/analyst/ask` response gains `answer_source`: `"template"` (TemplateLLM, `AI_PROVIDER=none`) or `"llm"`. Existing
fields unchanged. The analysis endpoints above import nothing from `app.analyst` and never depend on AI.

## 7. as_of and sealed behaviour
- `latest_sealed_as_of` is a calendar day (IST), not a trading day; a weekend or holiday as_of is valid and analysed on
  the bars that exist (bars after it never reach the analysis, as in 011).
- Point-in-time: all of 011's boundary rules apply unchanged (`B` = IST midnight of D+1; trades by trade time; seeds from
  `(user_id, D, name)`), so repeated calls return identical bodies.
- No caching, no persistence. Each call computes (a market-data fetch can take seconds); results are deterministic.

## 8. Tests to write (before the code)
T1 Route isolation: two users, each gets only their trips on all five endpoints; unknown trip id is 404 for the other user.
T2 Point-in-time: a trade or bar dated after `as_of` leaves every response byte-identical.
T3 Sealed: omitted `as_of` equals `latest_sealed_as_of`; `as_of` today/future is 422 `as_of_not_sealed`; naive/malformed 422.
T4 Parity: every number in the five responses equals the corresponding `AnalysisFacts` fact for the same inputs (and
   `analyse` output is unchanged by adding `analyse_detail`).
T5 Trip ids from 007 and 008 are equal for the same input; mismatch fails loudly.
T6 Display rule: every numeric field has `value` + `display` (+ reason when null); property test that no `display` is
   "0", "0.00%", "₹0.00" or "" when `value` is null; `x_display` exists for every Decimal field of the existing schemas
   (schema-walking test, fails when a new Decimal field has no display sibling).
T7 Unavailable fixtures (no series, coverage undeclared, <10 trips, <10 per regime): HTTP 200, marker, reason, `sample`
   text correct ("9 of 10 trips needed"); no 0 anywhere.
T8 No float, NaN or inf in any JSON body; all Decimals canonical (no exponent).
T9 Alternatives: every trip carries a label; `alternatives_note` text present in `meta`.
T10 Boundaries (AST): `api/routes/analysis.py` and its schemas import no `app.analyst`, no httpx, no quant result
    types beyond the service's read types; `domain/` and `quant/` unchanged (git diff); existing 2346 tests still pass.
T11 Backward compatibility: existing endpoint tests pass untouched; new `*_display` fields are additive.
T12 `answer_source` is `template` under `AI_PROVIDER=none`; analysis endpoints work with no AI configured.
T13 Offline: all tests run with recorded bar fixtures, no network, no DB env file.

## 9. Acceptance criteria
A1 T1-T13 pass and the full suite stays green. A2 Every number the UI needs has a server display string. A3 No new
statistic, formula or threshold. A4 Spec files stay under 200 lines.

## 10. Out of scope
New analytics; persistence or a trial registry; caching or background jobs; writing endpoints; per-trip listing of trips on
excluded listings; trading-day calendars; localisation beyond INR/Indian grouping; auth; a document retriever; changing
analyst wording or the number guard; any frontend code.
