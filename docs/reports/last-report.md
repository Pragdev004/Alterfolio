# Feature 013 Phase C1 report (2026-10-18)

## Backend (commit `815cc2f`)
- Aggregate `mean_excess_direction` is `inconclusive` when `ci_lower <= 0 <= ci_upper`; new `mean_excess_direction_text` = "not distinguishable from zero".
- New `portfolios_text` on each outcome: "500 portfolios built from 10 other Nifty Bank stocks" (Nifty baseline: "... from N Nifty 50 stocks").
- Histogram text drops the "0 the same" clause when no tie.
- Tests first (red), then code. **Two approved assertions were updated because the owner's change alters them**: the mean-direction
  check in `test_direction_is_explicit_and_follows_the_sign` (now allows `inconclusive`) and the two histogram text pins (no "0 the same").
- Full suite: **2488 passed, 0 failed, 0 skipped**, using a throwaway local PostgreSQL 16 (with `vector`), a no-vector database and the
  local Ollama (`ALTERFOLIO_TEST_*` env vars). Without those env vars 10-90 tests skip, as before.
- Spec 013a section 14 records the changes.

## Frontend (`frontend/`)
- Scaffold: Vite + React 18 + TS, tokens.css (layers, light default, dark tokens), Source Sans 3 self-hosted, React Router with `?as_of=`,
  TanStack Query, types generated from `openapi.json` (`gen:openapi`, `gen:types`, `check:types`), dev proxy, ESLint rule forbidding
  `toFixed`/`toLocaleString`/`Intl.NumberFormat`/`parseFloat`/`parseInt`, and `Number()` outside `shared/ui/geometry.ts`.
- Shared: chart header, Figure/Unavailable/Reason, status code, direction (no arrow or colour for inconclusive/level), too-few sentence,
  histogram (SVG + visible text + bar titles), volatility band, skeleton/empty/error/not-final/analyst-offline states.
- Screens: Trip list and Trip detail (as the mockup). Holdings/Costs/Ask/Upload show "not built yet" (C2).
- Tests: 73 vitest (MSW, fixtures recorded from the real 013a API via `backend/scripts/record_fixtures.py`), including WCAG contrast of
  light and dark tokens, a source scan and a test that the ESLint rule fires. 1 Playwright smoke (list -> detail -> Unavailable word + reason): passes.
  `tsc`, `eslint`, `vite build`, `check:types` clean.
- Run against the real backend (`backend/scripts/dev_server.py`, synthetic world, real API) with the Vite proxy; screenshots in
  `docs/reports/c1-screenshots/` (trip list and detail, desktop and mobile).

## Deviations and notes
- The as-of picker is an always-visible labelled date input (max = latest sealed day) instead of a "Change date" button.
- Latest bar is shown only when the as-of equals the latest sealed day (meta has no per-date bar), so the header never overstates.
- The trip list Note column is filled only for trips that were not compared (the same Nifty reason on every row was noise).
- `g` chords are in (h/t/c/a/u); there is no UI toggle to disable them yet.
- Data is the synthetic test world, not the owner's real trades; real-data run is untested.
- Not done: Holdings, Costs, Ask, Upload (C2). Session stayed above 15%.
