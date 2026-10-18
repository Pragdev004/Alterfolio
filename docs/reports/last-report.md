# Feature 013 Phase C2 report (2026-10-18)

## Fixes from the owner's live check
1. **Horizontal overflow.** Two causes found and fixed: a single-column grid track that could not shrink (~700px), and the trip table's
   `nowrap` listing name widening the page with a long name (reproduced at 1890 and 1366px). Long text now wraps. Playwright checks no
   sideways scroll and the rail in view at 1920, 1366, 1000, 700 and 390px on every screen, plus a long-text case; reverting the CSS makes it fail.
   I could not reproduce your exact 1890px state with synthetic data (your backend on :8000 was untouched); the long-name case is the closest cause I found.
2. Disclaimer removed from the rail; the footer keeps it (now outside `<main>`, so it is a real landmark).
3. `<html lang="en-IN">` was already set (now tested). The server's formatted date sits next to the native date input.
4. Chart header shows "Latest bar: No price data yet." (server sentence) when `last_bar_date` is null.

## Built
Upload, Holdings (PARTIAL note from the server), Costs (archetype metrics labelled unitless; raw `details` deliberately not shown because they
carry unformatted numbers), Ask (template / unverified labels, citation chips linking to the screen with `?as_of=`, "Analyst offline — your numbers
are still here"), and a rail checkbox that turns the `g` shortcuts off (remembered in the browser).

## Backend changes (suite: 2490 passed, 0 failed, 0 skipped, with local PostgreSQL, a no-vector DB and Ollama)
- `POST /api/analyst/ask` returns 503 `ai_provider_not_configured` for a missing/unknown provider (it was a 500; rule 5 of CLAUDE.md).
- Plain sentences: "No price data yet." and "This habit's cost has no separate fee part." (replacing "This is not available.").
- New dev worlds `holdings`/`valued`, fake quotes, ask/import/meta fixtures recorded from the real API (`record_fixtures.py`).

## Frontend verification
125 vitest tests (MSW, recorded fixtures), 10 Playwright tests (smoke: upload -> trips -> trip detail -> Unavailable word and reason; overflow),
`tsc`, `eslint`, `vite build` and the generated-types check all clean. Screenshots of every screen, desktop and mobile: `docs/reports/c2-screens/`.
Nothing used your real tradebooks; uploads use the invented `tradebook_synthetic.csv`.

## Opus review (14 findings) and what I did
Fixed: date input fought typing and the header could show the wrong date (draft state, full-date commit, "…" while loading); trip list lacked the
alternatives note, caveats, limitations and analysis errors; several Unavailable values had no reason (fees known, sample, regimes, volatility band,
across-trips); trip detail had no h1 while loading/erroring; Ask answers now show their date, clear on edit, and link with `?as_of=`; Ask shows an error
when `/meta` fails; invented "no price on the closing date" cause removed, unknown interval position no longer renders "sits ."; histogram refuses to
draw from null values and clamps the marker; `.dir` text no longer spills under neighbouring columns; vacuous tests replaced (regime sentence,
unknown-fee count, footer landmark); trip ids encoded in links; Holdings header says Unavailable when prices fail; lint now rejects unary `+` and
arithmetic on `.value`.
Partly addressed: phone tables keep their table markup restyled as blocks. I added the alternatives label to the phone row but did not add explicit ARIA
table roles, so some screen readers may announce phone rows without column headers. Open, worth a decision.
Not changed: a few counts are still composed from raw integers in the browser ("N trips · …", "the first N of M", "(N trips)"); only 013a could supply those strings.

## Notes
- Costs shows Disposition/Chasing cost as the server's "₹0.00" for small samples; that is the server's number, not a UI default.
- Not verified: any run on your real data, and the g-shortcut toggle in a browser with blocked storage.
