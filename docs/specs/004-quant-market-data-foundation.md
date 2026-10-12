# 004 Quant market-data foundation (as built)

Plan: `docs/plans/004-quant-market-data-foundation.md` (decisions F1-F6). No route, migration, table, cache or new
dependency. Features 001-003 behavior is unchanged. Not built: returns, portfolio series, volatility, drawdown, risk,
corporate actions, backtesting, AI, any non-Yahoo provider. Those belong to Feature 005 and later.

## Layout
- `app/providers/market/history_port.py`: `HistoricalBarProvider` Protocol, `RawBar`, `RawBarBatch`, `BarFailure`,
  `BarFailureKind` (`NOT_FOUND`, `PROVIDER_ERROR`, `INVALID_RESPONSE`). Stdlib + domain only; no vendor name or field.
- `app/providers/market/yahoo.py`: `YahooProvider.get_daily_bars` added beside the 003 quote code (quotes unchanged).
- `app/quant/market_data/`: `bar.py` (`MarketBar`), `series.py` (`MarketSeries`), `provenance.py` (`DataProvenance`),
  `fingerprint.py`, `exchange_time.py` (`local_date`). Stdlib + domain only; pure (no clock, no randomness, no float).
- `app/services/market_series.py`: `MarketSeriesService`, `build_series`, `ResolvedSeries`, `SeriesUnavailable`,
  `SeriesAttempt`, `AttemptOutcome`. It reuses `quote_candidates` from `portfolio_summary` (NSE then BSE).
- Dependency direction: services -> history_port, services -> quant, quant -> domain, providers -> domain. Providers never
  import quant; quant never imports providers or services; only `yahoo.py` imports httpx; only `api/main.py` may import
  the Yahoo adapter.

## Numeric values (provider-reported, exact)
- Yahoo JSON is parsed with `json.loads(parse_float=Decimal, parse_int=Decimal)`; `NaN`/`Infinity` constants are rejected.
  Open/high/low/close/adjusted_close are the exact Decimals of the JSON text: no float, no rounding, no normalization.
  `105.50` stays `105.50` in `RawBar` and `MarketBar`.
- Guards reject, never alter: finite, `0 < x < MAX_AMOUNT` (10^15), exponent within [-20, 13]. `MarketBar` re-checks them.
- Volume: int >= 0. Zero is valid. Negative, non-integral, bool and non-numeric volume are invalid. The adapter also
  rejects volume >= 10^15 (resource-safety guard so an absurd exponent never becomes a huge int).
- Canonical Decimal serialization is a separate, later step. `canonical_decimal` renders the exact value as plain
  fixed-point text with trailing zeros stripped (`105.50` -> `105.5`, `1E+3` -> `1000`), from `as_tuple()` so no Decimal
  context can round it. `to_dict()` and the fingerprint both use it. It preserves the numeric value, not the JSON text.

## Provider timestamps and session dates
- `RawBar.timestamp` / `MarketBar.timestamp` is the provider's bar timestamp as aware UTC, preserved exactly, any time of
  day (03:45Z, 03:30Z, 12:45Z, 09:44Z all occur). No close time is invented. `MarketBar` has no `price` accessor.
- `session_date` = date of `timestamp + exchange_utc_offset`. The Yahoo adapter requires `meta.gmtoffset == 19800` and
  `meta.currency == INR`, then exposes only `exchange_utc_offset = timedelta(seconds=19800)`; `gmtoffset` never crosses the port.
- `MarketSeries` requires `session_date == local_date(timestamp, offset)`, strictly increasing timestamps, unique session
  dates, `|offset| <= 14 h`, at most 6,000 bars. No gap is filled, resampled or aligned.

## Yahoo daily-bar request and mapping
`GET /v8/finance/chart/{SYM}.NS|.BO` with exactly four query parameters: `interval=1d`, `period1` (start 00:00 IST epoch),
`period2` (end + 1 day 00:00 IST epoch), `includeAdjustedClose=true`. `events=div,splits` (any `events=`) is not sent.
Range: `start <= end`, `(end - start).days <= 3660`; a bad range, a non-date or a naive `retrieved_at` is `ValueError`.
- 404 or a "Not Found" error object: `NOT_FOUND`. 429, 5xx, other non-200, timeout, network: `PROVIDER_ERROR`.
- `INVALID_RESPONSE`: bad JSON or shape, currency not INR, `gmtoffset` not 19800, column length mismatch, missing
  adjusted-close column, bad timestamp, non-increasing or duplicate session dates, partly-null row, price or volume
  outside the guards, more than 6,000 bars.
- A row whose every field is null is an empty row: excluded, counted in `empty_rows_excluded`, never filled or zeroed.
  A valid answer with no usable rows is an empty batch, not `NOT_FOUND`.
- Short history is valid: a first bar months after `start`, or a single bar, is returned as a partial batch. The adapter
  does not drop bars outside `[start, end]`. The timeout is the per-request httpx timeout (3 s); one request per call.

## Eligibility and the retrieval-time invariant (service)
1. `MarketSeriesService` reads its injected clock once per `resolve_*` call. The clock must be timezone-aware.
2. It passes that exact instant as `retrieved_at` to every `get_daily_bars` attempt of the call.
3. `build_series` requires `batch.retrieved_at == retrieved_at` (instant equality). A mismatch (later, earlier, naive) raises
   `ValueError`, which the service records as `AttemptOutcome.INVALID_BARS` and then falls back like any invalid batch.
4. Eligibility uses only that supplied instant: a bar is eligible iff `session_date < local_date(retrieved_at,
   batch.exchange_utc_offset)` (strictly before the exchange-local date; not a market-close or finality claim). A provider
   cannot move this boundary, so it cannot make a future bar eligible. Ineligible bars are excluded before conversion
   (they cannot cause a validation error) and counted in `ineligible_bars_excluded`.
5. The series has `cutoff = retrieved_at` and `observed_through = local date - 1 day`.

## Series, provenance, point-in-time
- `DataProvenance`: `source`, `request_start`, `request_end` (kept even if not covered), `retrieved_at`, `rows_returned`,
  `empty_rows_excluded`, `ineligible_bars_excluded`, `eligible_bars_at_fetch`, first/last eligible session date (None when 0),
  `numeric_policy = PROVIDER_REPORTED_VERBATIM`, `close_semantics = provider-defined`,
  `knowledge_basis = AS_FETCHED_AT_RETRIEVAL`, `fingerprint_version = 1`. No coverage boolean (F2).
- Coverage is facts only: `bar_count`, `first_session_date`, `last_session_date` over the current bars. No key or text says
  "covered", "complete" or "full"; sufficiency is Feature 005's decision.
- `truncated_to(T)` only narrows: `ValueError` if T is naive or later than the current cutoff (so never after
  `retrieved_at`, and a truncated series cannot be widened); `T == cutoff` is allowed. It keeps bars with
  `session_date < local_date(T)`, sets `cutoff = T`, keeps provenance unchanged, and recomputes the fingerprint. It is not an
  as-known-at-T query: values (notably `adjusted_close`) are as restated at retrieval.
- Fingerprint: SHA-256 of canonical JSON (sorted keys, no spaces) of version, source, instrument, currency, `"1d"`, and per
  bar `[timestamp Z, session_date, o, h, l, c, adj, volume]`. Excludes `retrieved_at`, counts and the requested range.
- `to_dict()`: `schema_version` 1, `as_of` (the cutoff), `provenance` (with `fingerprint`), `inputs`, `values`; Decimals as
  canonical strings, offset as integer seconds.

## Listing resolution
`resolve_for_holding`: ISIN holding tries NSE then BSE; a NULL-ISIN legacy holding tries its single listing only
(`legacy=True`). `resolve_series(listings, ...)` uses the given order, de-duplicated. The first listing that yields a series
with at least one eligible bar wins; series are never spliced. Fallback on `NOT_FOUND`, `INVALID_RESPONSE`, no eligible
bars, and invalid bars (validation failure, wrong-listing answer, `retrieved_at` mismatch, malformed outcome). No fallback
on `PROVIDER_ERROR` (including a provider that raises, recorded with the exception class name only). A short series is
returned as is. Results: `ResolvedSeries(series, attempts, legacy)` or `SeriesUnavailable(attempts, legacy)`; every try is a
`SeriesAttempt(listing, outcome, detail)`. Provider problems are never raised.

## Tests (offline; synthetic `ZZ` symbols; no live Yahoo)
`test_history_port.py`, `test_market_bar.py`, `test_market_fingerprint.py`, `test_market_series.py`,
`test_market_data_purity.py` (quant types), `test_market_yahoo_history.py` (`httpx.MockTransport`),
`test_market_series_service.py` (fake non-Yahoo provider, eligibility, fallback, `retrieved_at` invariant),
`test_import_boundaries.py` (provider/quant/service boundaries, no float). Shared builders: `tests/market_helpers.py`.

## Known limits
- `services/market_series.py` imports `quote_candidates` from `portfolio_summary`, which pulls the ledger and SQLAlchemy in
  transitively (the module's own imports are framework-free). A pure home for it is possible cleanup.
- Volume bound (10^15) and the span reading are implementation decisions recorded in the plan.
- `MarketSeries` does not enforce INR or cross-check provenance against bars; `RawBar` is not validated at the port.
- The live Yahoo endpoint is not exercised by any test.
