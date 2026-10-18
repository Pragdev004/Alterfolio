# Spec 013: Frontend
Status: PROPOSED, Phase A (spec only). Owner decisions applied 2026-10-18. Depends on Feature 013a
(`013a-analysis-read-api.md`), which must be delivered before any analysis screen is built. No design, stack or code yet.
Reads: `CLAUDE.md`, `README.md`, specs 006-011, 013a, `backend/app/api/`.

## Context rules (fixed, from the owner)
- Numbers shown to the user go through the backend display formatter. Never format money or percentages in the frontend.
- The user uploads their oldest tradebook first (import is order-aware).
- Any "alternatives" label must say these are same-sector or same-universe alternatives, never a prediction.

## 1. Goal
Let the single local investor (U7) upload tradebooks, see holdings, see their closed round trips, see whether each decision
looks like skill or luck against similar alternatives, see behaviour costs, and ask the analyst. It displays deterministic
backend output and computes nothing. Educational, not financial advice; no BUY/SELL wording, no profit claims.

## 2. Decisions (owner, 2026-10-18)
D1 Backend feature 013a (read-only analysis endpoints) comes before any UI. D2 The server adds display strings next to
every number on every endpoint the UI uses (trades, holdings, summary, import, analysis); the frontend never formats.
D3 013a exposes only what is already computed; no new statistics. D4 Analysis screens never depend on AI; analyst 503 or
network failure shows "Analyst offline — your numbers are still here"; template answers are labelled as template.
D5 Default `as_of` is the server's latest sealed day, never today; 422 shows "Data for that date isn't final yet."
D6 Verdict copy approved, with the server's sample text "X trips · N needed" (N from the backend). D7 Manual entry/correct/void out;
holdings screen in. D8 CORS and stack are Phase B.

## 3. Endpoints the UI uses
User is always the server's local user; the client sends no user id. Ledger errors: `{"detail": {"code","message"}}`.
Every Decimal/ratio in a response has a server display string (013a section 4): the UI renders `display`, never `value`.
| Endpoint | Used by | Notes |
| --- | --- | --- |
| `GET /health` | all | network failure vs 5xx are distinct messages |
| `POST /imports/tradebook` multipart `file` | S1 | 201 counts, first 200 `rejected` rows, `quarantined_isins`, `fees_taxes_provided`; 422 `invalid_import_file`/`oversell`; 409 `ledger_busy` |
| `GET /portfolio/holdings` | S6 | holdings with `*_display` fields |
| `GET /portfolio/summary` | S6 | `valuation_status`/`valuation_text`, per-holding `quote_status`; totals null when partial |
| `GET /trades`, `/trades/{id}` | S6 (read only) | trade list drill-down, `*_display` fields |
| `GET /api/analysis/meta` | S2-S5 | `latest_sealed_as_of`, thresholds, `alternatives_note`, limitations |
| `GET /api/analysis/trips`, `/trips/{trip_id}` | S2, S3 | summary, per-trip luck, alternatives label, regime tag, `sample` text, caveats |
| `GET /api/analysis/regimes` | S3 | LOW/NORMAL/HIGH blocks with `sample` text |
| `GET /api/analysis/biases` | S4 | three bias costs, archetype, `sample` text |
| `POST /api/analyst/ask` `{question<=2000, as_of}` | S5 | `{text, citations, verified, as_of, attempts, answer_source}`; 422 `as_of_not_sealed` |
Not used: `POST /trades`, `/trades/{id}/correct`, `/trades/{id}/void` (manual entry is out of scope).
013a is implemented: the display siblings and `/api/analysis/*` exist (shapes in `013a-analysis-read-api.md`).

## 4. Screens
S1 Upload tradebook
- Choose CSV, show name and size, reject > 2 MiB client-side (server still enforces). Show before upload: "Upload your
  oldest tradebook first." After 201: counts, rejected rows (line, code, message), quarantined ISINs, and if
  `fees_taxes_provided` is false say charges are unknown, not zero.
- On `oversell`: explain a sell had no earlier buy; upload the earlier tradebook first. Keep the file selected on failure.
S2 Trip list
- Default `as_of` = `latest_sealed_as_of` from `/meta`, shown and changeable (date must be before today; the server decides).
- One row per trip: listing, open and close dates, actual return (display, "fees excluded"), luck status or reason. Gated
  trips are listed with their reason. Excluded listings are listed with reason and their trip count.
S3 Trip detail, luck test and regime split
- Luck: actual return vs alternatives (percentile, excess, mean alternative return, picks), the alternatives label from the
  server, and `alternatives_note` ("Same-sector or same-universe alternatives, not a prediction") on every luck view.
- Caveats from the server always visible: static universe/survivorship, price proxy, fees excluded, heuristic small sample.
- Regime: the trip's LOW/NORMAL/HIGH tag or reason; block summaries with `sample` text; Unavailable below the threshold.
S4 Behaviour costs
- Disposition, chasing, overtrading costs as displayed (lower-bound and fee notes included), unknown-fee counts, archetype
  or Unavailable with reason. Observational wording only.
S5 Ask the analyst
- Question and as-of (default latest sealed). Show `text`, `verified`, citations, and a "Template answer" label when
  `answer_source` is `template`. `verified=false` is labelled "Unverified: showing the raw facts", never a normal answer.
- 503, timeout or network failure shows "Analyst offline — your numbers are still here" and leaves S2-S4 untouched.
S6 Holdings
- Holdings table and summary. PARTIAL/UNAVAILABLE uses `valuation_text` and per-holding `quote_status` reasons.

## 5. "Unavailable is never 0" (UI rule)
- A value is a number (its `display`) or the word "Unavailable" plus its reason, same place and weight. Never "0", "0.00%",
  "-", an empty cell, or a blank chart point.
- The UI keys off `value: null` / `display: "Unavailable"` and never treats null or absent as 0. A genuine zero is shown as
  the server's `display`.
- No client-side sums, averages, rankings or colour scales over values that may be Unavailable. Order comes from the
  server; Unavailable sorts last with its label.
- No bars, gauges or sparklines for Unavailable values; charts show a gap and the reason.
- Partial totals say so ("3 of 5 holdings valued") and are never shown as the portfolio total.

## 6. Verdict wording when there are too few trips
- Needs >= N trips (N from `/meta` thresholds: luck, per regime, behaviour; currently 10 each). Below N the backend returns
  Unavailable and a `sample` object; the UI shows the reason and the server text, e.g. "Not enough closed trips to say
  anything yet. 7 trips · 10 needed". The UI never composes the count itself.
- Forbidden: "not significant", "no skill", "you are lucky/unlucky", scores, grades, colour verdicts, defaults of 0.
- With 1 to N-1 usable trips, per-trip numbers and means may appear but never as a verdict.
- With enough trips, wording is positional and hedged: where the interval sits relative to zero, plus "heuristic, small
  sample, not proof of skill or luck". "Skill" is never asserted.

## 7. Empty, loading and error states (each screen)
- Empty: no trades -> S1 call to action. Trades but no closed trips -> "Trips appear when a position is fully sold."
  No rejected rows -> no table. No analysis for a date -> show the server's Unavailable reason.
- Loading: labelled, never a bare spinner. Upload: "Importing". Analysis and ask: "Fetching market data and computing";
  submit disabled while pending.
- Error: network down, 4xx and 5xx get distinct messages; show server `code` and `message`, mapped to plain language where
  known. 422 `as_of_not_sealed` -> "Data for that date isn't final yet." 409 `ledger_busy` -> retry. 404
  `analysis_trip_not_found` -> back to the list. One failed section never blanks another; errors are never shown as empty.
- Partial: PARTIAL valuation, excluded listings and Unavailable analyses are explained states, not errors.

## 8. Acceptance criteria
- A1 No money or percentage is formatted in frontend code; a test fails if a numeric string is parsed or formatted there.
- A2 Every Unavailable fixture renders the word and reason, never 0 or blank (one test per screen).
- A3 Fewer than N trips renders the required copy with the server's "X trips · N needed" text and no verdict.
- A4 `verified=false` and `answer_source=template` are labelled; the analyst-offline state leaves other screens working.
- A5 Every state in section 7 has a test; `oversell` and `as_of_not_sealed` show their specified copy.
- A6 Every luck view shows the alternatives note; no prediction language anywhere.
- A7 Frontend tests pass with no backend, network or AI credentials (recorded fixtures of 013a responses).
- A8 The frontend changes no backend behaviour; backend needs go through 013a.

## 9. Out of scope
Visual design, brief and stack (Phase B), CORS/proxy (Phase B). Auth and multi-user. Manual trade entry, correct and void.
Charts of portfolio value, benchmarks (Nifty baseline unavailable), pairs/backtest UI, document upload or retrieval UI,
mobile apps, offline mode, report export, any recommendation or rating, client-side calculation of any financial number,
persistence of analysis results (deferred until after 012).
