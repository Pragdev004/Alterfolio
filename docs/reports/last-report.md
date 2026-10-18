# Last report: Phase B review round (013a.1 + mockup)
Date: 2026-10-18. Scope: the owner's seven review items. Backend tests first, then code, then docs and mockup.

## Result
- Full backend suite: **2474 passed, 0 failed, 0 skipped** (`python -m pytest -q -rs`, live PostgreSQL and Ollama env loaded).
- Baseline before this round: 2442 passed. New/changed tests are in `tests/test_analysis_api.py` and `tests/test_analysis_display.py`
  (written first and run RED: 43 failures before any code).
- No approved (pre-013a) test was changed. Only this session's own 013a tests changed, for the new formats
  (`"9 trips · 10 needed"`, `reason_text` keys, whole-number percentiles).

## What changed (the seven items)
1. **Reconciled data:** mockup now reads picked 7 + left out 2 = 9 in the label; 1 of the 7 had no exit price, so portfolios are
   drawn "from 6"; chart prepared Sun 18 Oct 2026, latest bar Fri 16 Oct 2026 (before today, Mon 19 Oct).
2. **Plain English:** `reason_text` beside every reason (`domain/display.py::reason_text`, tested against every 007/008 code);
   exclusions carry ticker + exchange + sentence, no ISIN shown; existing summary reasons are plain sentences.
3. **Regimes:** `regimes.none_ready_text` ("Not enough trips in any regime yet: Low 3, Normal 9, High 2 (10 needed each)");
   sample text is `N trips · M needed` everywhere.
4. **Percentile:** whole percent, half-even (`61%`), via the server formatter. The analyst's own text is unchanged.
5. **Footer:** the "server's own text" line is gone from the product; the mockup carries a separate "Design mockup" strip.
6. **Histogram:** `trips/{id}` returns `histograms.ALT|NIFTY` (20 equal bins spanning the trip's return, `marker_bin`, text
   equivalent). The mockup replaces the position strip with it, with a dashed marker, tinted "returned less" bars and the text.
7. **Mobile:** tables become compact two-line rows (title + status/value, then one line of figures).
013a.1: `excess_direction` / `mean_excess_direction` (ahead|behind|level|null); Unavailable outcomes have null counts.

## Needs your eye
- **One `quant/` change.** The 500 portfolio returns were computed and then discarded, so `BaselineOutcome` now retains them as
  `portfolio_returns` (optional, `compare=False`, not in JSON, equality or fingerprint). Two lines in `quant/luck_test`. All quant
  tests pass unchanged.
- Analyst text (`/api/analyst/ask`) still shows percentiles with two decimals; only the analysis API uses whole percents.
- Histogram bins are counts over the drawn portfolios and the trip's return; no new statistic. `text` quotes the stored `beaten`
  and `ties` counts.
- Mockup data is synthetic; the histogram counts are hand-set to match `beaten=305` of 500.

## Files
`backend/app/{domain/display.py, schemas/analysis.py, schemas/summary.py, services/analysis_view.py, api/analysis_presenter.py,
quant/luck_test/{types,analysis}.py}`, tests above, `docs/specs/013*.md`, `docs/design/013-frontend-design.md`,
`docs/design/mockups/trip-detail.html`, `docs/design/mockups/screenshots/trip-detail-{desktop,mobile}.png`.
