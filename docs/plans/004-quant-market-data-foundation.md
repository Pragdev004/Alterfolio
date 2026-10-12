# Feature 004: Quant Market Data Foundation

**Status: APPROVED (owner, 2026-10-12).** Condensed copy of the approved plan; the F1-F6 decisions below are verbatim.
Implemented (working tree, uncommitted): plan steps 1-6. As-built spec: `docs/specs/004-quant-market-data-foundation.md`.
Step 7 (final verification, commit only when asked) remains. Step 4 added the rule that a batch's `retrieved_at` must equal
the instant the service supplied (spec section on eligibility).
Source of the full text: `~/.claude/plans/pasted-content-id-8a87-feature-compressed-seal.md`.

## Context
Stage 2 (Quant V1) needs historical daily bars before any return/risk work. Feature 003 only has last-trade quotes.
Feature 004 builds the pure foundation: `MarketBar`, `MarketSeries`, provenance + fingerprint, a historical-bar port, the
Yahoo daily-bar adapter, listing resolution, point-in-time truncation. Out: returns, portfolio series, volatility,
drawdown, risk metrics, corporate-action reconciliation, any price-basis choice for returns.
Fixed constraints (user decisions 1-10): daily only; bar timestamp = provider timestamp in UTC (no invented close
time); `close` and `adjusted_close` both explicit; no basis chosen; an ineligible (not strictly before the retrieval-local
date) bar never enters a historical series; nothing fabricated or forward-filled; no returns/portfolio/risk.
Observed (live, RELIANCE.NS): bar timestamp usually session START (03:45Z); `close` split-adjusted, `adjclose` also
dividend-adjusted; today's bar returned live while session open; meta.gmtoffset 19800.
Step 0 (DONE, 17 symbols, 2021-2026): every value exactly float32-representable; 7-significant-digit rounding FAILS the
float32 round-trip (`yahoo-float32-7sig-v1` REJECTED); OHLC ordering holds; all-null rows exist, no partial-null rows; zero
volume exists (606 ETF bars); bars at 03:45Z (usual), 03:30Z, 12:45Z, ~09:44Z; Yahoo can return a valid 200 with far less
history than requested (two BSE symbols returned one bar).

## 0. FINAL DECISIONS (supersede anything below that disagrees)
- **F1 Precision = provider-verbatim.** Parse every Yahoo JSON number directly to `Decimal` (`json.loads(parse_float=
  Decimal, parse_int=Decimal)`), no float, no rounding, no fixed-dp or significant-digit normalization. This preserves
  the provider-reported numeric value; it does NOT claim to recover a "true" market price. The fingerprint hashes the
  canonical form of those exact Decimals. No `normalization_id` exists anymore.
- **F2 Short coverage is valid.** A valid response with less history than requested is NOT rejected solely because the
  first bar is later than the requested start. A partial `MarketSeries` is returned. Never imply the requested range was
  covered; no coverage boolean. Feature 005 decides sufficiency.
- **F3 Any provider timestamp accepted.** Preserve the provider timestamp exactly as aware UTC; no time-of-day check
  (03:45Z, 03:30Z, 12:45Z, 09:44Z all valid); `session_date` derived from the exchange offset; no invented close time.
- **F4 All-null rows:** excluded, counted, never filled/zeroed; neutral wording "empty row"/"excluded", never "incomplete".
- **F5 Zero volume is valid.** Only negative, non-integer, bool or non-numeric volume is invalid.
- **F6 Request:** no `events=` parameter. Only fields needed for daily bars + `adjusted_close`.
- **Owner clarification (2026-10-12):** "provider-verbatim" preserves the exact numeric VALUE, not the JSON text
  formatting. `to_dict()` and the fingerprint both use the exact canonical Decimal text (plain fixed-point, trailing zeros
  stripped, `105.50` -> `105.5`). Never a float, never rounded.

## 1. Contradictions found (flagged)
- C1: bar timestamp = session START + point-in-time. Keying truncation on the timestamp would leak a day's data after T.
  Resolution: eligibility and truncation key on session date vs the exchange-local date.
- C2: design.md puts `MarketBar` in `quant/market_data` but `providers -> quant` is not an allowed edge. Resolution: section 2.
- C3: `v1-lineage.md` P4 says bar timestamp = close; it applies from the Backtesting stage; record in lineage that Stage 5
  revisits it.
- C4: the 003 boundary test hard-codes one port module and one httpx file; extend it, never weaken it.

## 2. Placement and import boundaries
- `app/providers/market/history_port.py` (stdlib + `app.domain`): `RawBar`, `RawBarBatch`, `BarFailure`, `BarFailureKind`
  (NOT_FOUND | PROVIDER_ERROR | INVALID_RESPONSE), `HistoricalBarProvider` Protocol. RawBar lives here (provider-owned,
  provider-neutral, no Yahoo field names).
- `app/providers/market/yahoo.py`: add `get_daily_bars` to `YahooProvider` (httpx stays confined to this file; reuse
  `yahoo_symbol`, client, budget logic). 003 `port.py` and quote behavior untouched.
- `app/quant/market_data/{bar,series,provenance,fingerprint,exchange_time}.py` (stdlib + `app.domain` only).
- `app/services/market_series.py`: converts `RawBar -> MarketBar`, applies the eligibility rule (section 5), resolves
  listings, calls the provider; reuses `quote_candidates` from `portfolio_summary` (NSE-then-BSE). No
  sqlalchemy/fastapi/pydantic/httpx.
- Edges: `services -> providers (history_port, port only)`, `services -> quant`, `quant -> domain`, `providers -> domain`.
  Forbidden and tested: `providers -> quant`, `quant -> providers/services/...`, httpx outside `yahoo.py`.
- No domain additions. No `zoneinfo` (no tzdata on Windows). Yahoo `meta.gmtoffset` is read and checked inside the Yahoo
  adapter only (must equal 19800 for NSE/BSE else `INVALID_RESPONSE`) and crosses the port as `exchange_utc_offset`.

## 3. Historical-bar provider interface
`get_daily_bars(instrument, start: date, end: date, retrieved_at: datetime) -> RawBarBatch | BarFailure`
- `start`/`end`: inclusive exchange-local (IST) session dates; `start <= end`, span <= 3,660 days (`(end - start).days <= 3660`); naive `retrieved_at` or
  bad range = `ValueError` (programming error, like 003).
- `RawBar`: `timestamp` (aware UTC), `session_date` (adapter-derived), `open`, `high`, `low`, `close`, `adjusted_close`
  (Decimal), `volume` (int). No Yahoo field names, no raw payload, no provider metadata.
- `RawBarBatch`: `instrument`, `bars` (provider order), `currency`, `source` (opaque id), `retrieved_at`,
  `exchange_utc_offset: timedelta`, `rows_returned`, `empty_rows_excluded`. No normalization field.
- Never raises for provider/network/shape problems; returns `BarFailure(kind, detail)`.

## 4. Yahoo contract
`GET /v8/finance/chart/{SYM}?interval=1d&period1=<start 00:00 IST epoch>&period2=<end+1 day 00:00 IST epoch>&includeAdjustedClose=true`
Exactly these four query parameters: `interval=1d`, `period1`, `period2`, `includeAdjustedClose=true`.
`events=div,splits` (any `events=`) is NOT sent (F6; exact-URL test). `.NS`/`.BO` via `yahoo_symbol`. Parse with
`json.loads(text, parse_float=Decimal, parse_int=Decimal)`; volume must then be integral, converted to `int`.
Fields: `timestamp[]`, `indicators.quote[0].{open,high,low,close,volume}`, `indicators.adjclose[0].adjclose`,
`meta.{currency,gmtoffset}`. Mapping: 404/"Not Found" -> NOT_FOUND; 429/5xx/timeout/network -> PROVIDER_ERROR; bad shape /
currency != INR / gmtoffset != 19800 / array length mismatch / non-increasing or duplicate session dates / non-integral,
negative or bool volume / partially-null row / price Decimal exponent outside [-20, 13] -> INVALID_RESPONSE.
All-null rows are excluded and counted in `empty_rows_excluded` (F4). A valid answer with zero usable rows = empty batch
(not NOT_FOUND). Later-than-requested start is returned as-is (F2). No time-of-day check (F3). Volume 0 valid (F5).
Same 3 s / 20 s budget; bar cap 6,000.
Recorded implementation decisions (Step 3, owner-confirmed 2026-10-12):
- The defensive Yahoo volume bound `volume < 10^15` (`MAX_AMOUNT`) is intentional. It is a resource-safety guard so an
  absurd exponent cannot become a huge `int`. It does not alter F5: volume 0 stays valid; negative, non-integral, bool and
  non-numeric volume stay invalid.
- The 3,660-day request span is interpreted as `(end - start).days <= 3660`.

## 5. Daily-bar eligibility rule
A daily bar is eligible for the historical `MarketSeries` only when its session date is strictly before the batch's local
calendar date at retrieval: `(retrieved_at + exchange_utc_offset).date()`, via one pure helper `local_date(instant,
offset)` in quant (shared with truncation). Ineligible bars are excluded and counted (`ineligible_bars_excluded`).
This is a conservative eligibility rule, NOT a market-close assertion and NOT a claim the bar is final. Wording: "eligible",
never "complete"/"final". `observed_through = local_date(retrieved_at) - 1 day`.

## 6. Point-in-time truncation
`truncated_to(T)` is narrowing-only, NOT an "as-known-at-T" query.
- A series has a `cutoff`: `retrieved_at` when fresh, `T` after truncation. `to_dict()["as_of"]` is the cutoff.
- ValueError if T is naive or `T > cutoff` (no re-widening). `T == cutoff` is allowed (idempotent).
- Keeps bars with `session_date < local_date(T, offset)`. New immutable series; empty is valid; `cutoff = T`;
  `observed_through = min(old, local_date(T) - 1 day)`; provenance unchanged; fingerprint recomputed.
- Provenance `knowledge_basis = "AS_FETCHED_AT_RETRIEVAL"`: values (notably `adjusted_close`) are as restated at
  `retrieved_at`. Guarantee = "no bar on or after local_date(T)". As-known-at stays out of v1 (spec.md open question 5).

## 7. Price precision
Provider-verbatim (F1). No float, no rounding, no normalization in adapter, services or quant. The only numeric guards are
rejections: finite, `0 < x < MAX_AMOUNT`, exponent within [-20, 13]. Feature 005 owns any quantization or float crossing.

## 8. MarketBar / MarketSeries / provenance / fingerprint
- `MarketBar` (frozen): `timestamp` (aware UTC), `session_date`, `open, high, low, close, adjusted_close` (Decimal),
  `volume` int >= 0; `high >= max(open, close, low)`, `low <= min(open, close, high)`; no `adjusted_close` cross-check;
  **no `price` accessor** (basis not chosen). `close` = "provider close, split-adjusted as observed, not as-traded".
- `MarketSeries` (frozen): `instrument`, `currency` (INR), `bars` (tuple), `exchange_utc_offset` (|offset| <= 14 h),
  `cutoff`, `observed_through`, `provenance`. Invariants: strictly increasing timestamps, unique session dates,
  `session_date == local_date(timestamp, offset)`, <= 6,000 bars. No fill, resample or alignment (Feature 005).
- `DataProvenance` (frozen): `source`, `request_start`, `request_end`, `retrieved_at`, `rows_returned`,
  `empty_rows_excluded`, `ineligible_bars_excluded`, `eligible_bars_at_fetch`, `first/last_eligible_session_date_at_fetch`,
  `numeric_policy="PROVIDER_REPORTED_VERBATIM"`, `close_semantics="provider-defined"`,
  `knowledge_basis="AS_FETCHED_AT_RETRIEVAL"`, `fingerprint_version`. No coverage boolean (F2).
- Coverage as facts (F2): computed `bar_count`, `first_session_date`, `last_session_date` over the CURRENT bars. Nothing in
  code, JSON or docs says "covered", "complete" or "full".
- Fingerprint = SHA-256 hex of canonical JSON (sorted keys, no spaces) of `fingerprint_version`, source, instrument,
  currency, `"1d"`, and per bar `[timestamp Z, session_date, o, h, l, c, adj, volume]`. Decimals use exact canonical text
  from `as_tuple()` (no Decimal context rounding). Excludes `retrieved_at`, counts, requested range.
- `to_dict()`: `{schema_version: 1, as_of, provenance{..., fingerprint}, inputs{instrument, request{start, end}, ...},
  values{bar_count, first_session_date, last_session_date, bars}}`; Decimals as exact canonical strings.

## 9. ISIN -> listing resolution and fallback (`services/market_series.py`)
`resolve_series(listings, start, end)` (+ `resolve_for_holding`): NSE then BSE; NULL-ISIN legacy holding -> its single
listing, flagged `legacy=True`. One `retrieved_at = clock()` per call. First listing whose batch converts to a valid series
with >= 1 eligible bar wins; no splicing. Fallback on NOT_FOUND, empty/no-eligible-bars, INVALID_RESPONSE and bar-validation
errors; no fallback on PROVIDER_ERROR. Returns `ResolvedSeries(series, attempts, legacy)` or `SeriesUnavailable(attempts)`.

## 10. API, persistence, config
No HTTP route, no migration (Alembic stays 0002), no tables, no cache, no new dependency, no new settings.

## 11. Test strategy (offline; synthetic `ZZ` symbols; no real prices in docs)
- Quant: bar/series construction rejects and accepts (volume 0, timestamps 03:45Z/03:30Z/12:45Z/09:44Z), no-fill,
  point-in-time properties (incl. seeded randomized), coverage facts, `to_dict` shape, Decimal exactness.
- Fingerprint: stability, per-field sensitivity (incl. last digit of a 13-dp value), exclusions, `1186.4` == `1186.400`,
  exact canonicalization of a >28-digit Decimal, exponent-form inputs.
- Yahoo adapter (httpx.MockTransport): exact URL and exactly four params, no `events` (F6), lossless values (F1), 404/429/5xx/timeout/network,
  shape failures, all-null rows excluded and counted (F4), partial-null INVALID, gmtoffset/currency/length/duplicate-date,
  short-history and single-bar responses (F2), empty batch, budget, naive `retrieved_at`.
- Provider neutrality: `history_port.py` names none of `yahoo`, `gmtoffset`, `regularMarket`, `adjclose`, `priceHint`;
  exact field-name sets; a non-Yahoo fake provider drives the service path.
- Service: eligibility boundary at local midnight, NSE -> BSE fallback, PROVIDER_ERROR -> unavailable, legacy single
  listing, no splicing, attempts recorded, provider that raises is contained.
- Boundary tests extended (no weakening); 001-003 suites unchanged and green.

## 12. Steps
0. DONE (live sampling; provider-verbatim decision). 1. `history_port.py`. 2. `quant/market_data/`. 3. Yahoo
`get_daily_bars`. 4. `services/market_series.py`. 5. Boundary tests. 6. Docs (this file, `docs/specs/004-...`, README row,
lineage U12 recording F1-F6 + P4 note, CLAUDE.md status; all < 200 lines). 7. Full suite + `alembic heads` = 0002; commit
only when asked. TDD per step; each starts only on explicit owner go-ahead.

## Hardening review (2026-10-12), steps 1-2
Reviewed read-only; 204 focused tests green. Deliberately NOT added (not required by this plan): INR enforcement on
`MarketSeries`, provenance-vs-bars cross-validation, `RawBar`/`RawBarBatch` validation, a `retrieved_at` type check.
