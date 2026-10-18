# Plan 013a: Analysis read API
Spec: `docs/specs/013a-analysis-read-api.md` (wins on conflict). No change to `domain/` logic or `quant/`.

## Steps (tests first; each step ends with focused tests, then the full suite)
1. Tests T1-T13 written and run RED (`tests/test_analysis_api.py`, `tests/test_analysis_display.py`,
   `tests/test_analysis_boundaries.py`; repo test for `ledger_version` in `tests/test_analysis_api.py`).
2. `domain/display.py`: pure formatters (`format_inr`, `format_percent`, `format_price`, `format_date`, `format_datetime_ist`,
   `number()` -> `{value, display, unavailable_reason}`); `api/display.py` re-exports them and keeps `render_fact`.
3. `schemas/display.py`: `WithDisplay` base (wrap serializer adds `x_display` / `x_unavailable_reason`), typed fields
   `MoneyOut`, `PriceOut`, `QtyOut`, `WhenOut`; apply to Trade/Holding/Summary/Quote schemas (additive).
4. Service: `PortfolioAnalysisService.analyse_detail` (retains all luck groups, regime, bias, excluded trips; `analyse` output
   unchanged); `TradeRepository.ledger_version`; `services/analysis_view.py` (plain read types + builder + alternatives kind).
5. `services/analysis_read.py`: `AnalysisReadService` (meta, sealed default, cache keyed `(user, as_of, ledger_version)`).
6. API: `api/routes/analysis.py` (+ presenter), `AnalysisTripNotFoundError` (404), `answer_source` on `/ask`, wiring in
   `deps.py` and `main.py` (cache on `app.state`).
7. Docs: CLAUDE.md (status, architecture lines), specs README rows, spec 013a status, 013 dependency note.
8. Full suite (0 failed, 0 skipped, live DBs), Opus review of the final diff, fix, rerun, push.

## Decisions taken in the plan
- Stored alternatives labels (`alternatives: ...`) stay as they are: approved 014 tests pin them. The API derives
  `alternatives_kind` and the "Same-sector/Same-universe alternatives" label from them in one tested function.
- `ledger_version` = (row count, max `recorded_at`) of all the user's rows, so imports, manual trades, corrections and
  voids all invalidate the cache. Results with unavailable series are not cached.
- Trips on excluded listings are listed from the ledger (opening-buy id, dates) with no computed return.
- Bias `supporting_metrics` are shown as the quant's canonical text (their units are not declared); no formatting guess.
- Owner (a): six approved exact-dict tests may only gain `*_display` keys; raw values byte-identical; diff reported.
- "n of N needed" N comes from the existing constants: `LuckParameters.min_trips`, `RegimeParameters.min_trips_per_regime`,
  `BiasParameters.min_round_trips` (read from the dataclass defaults / config, no new constant).
- Archetype supporting metrics: shown unitless and labelled so; CLAUDE.md Known issues gains "declare units for behaviour
  archetype metrics".
