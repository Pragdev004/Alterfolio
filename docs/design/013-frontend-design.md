# Design 013: Frontend (Phase B)
Status: PROPOSED, awaiting owner review. Specs: `docs/specs/013-frontend.md`, `013a-analysis-read-api.md`. No app is scaffolded.
Mockup: `docs/design/mockups/trip-detail.html` (static, synthetic data). Mode: Operate (the user is in a task).
Provenance: direction rolled with the impeccable seed `ea4c7265`; product facts inferred from the specs and two owner answers
(desktop-first deliberate review, English only). `PRODUCT.md` holds the durable product truth.

## 1. Product understanding
- **Who:** a retail Indian investor (NSE/BSE, INR) reviewing their own past trades, mostly at a desk on an evening or weekend,
  with the room lit. They file contract notes and statements; they are not day-trading from this screen.
- **Job:** find out, trip by trip, whether a result looks like skill or luck, what their habits cost, and what the data cannot say.
- **The one feeling:** *honest, calm, nothing hidden.* Every gap is shown and explained. No score, no streak, no confetti, no
  colour that celebrates a gain or punishes a loss. Nothing moves unless the data changed.
- **Never:** casino (red/green flashing, leaderboards, "you beat 90%!"), hype, advice. The words BUY, SELL, skill-as-verdict never appear.

## 2. Visual direction and philosophy
**The Chart.** Indian Railways' reservation chart and PNR status page: a fixed-column printed list where every row carries a
short status code and nothing is left blank. The idea transfers because the product's job is the same: a row is either
confirmed, waiting, or cancelled, and the reader is told which and why.
- **Fixed columns that never move** (donated by the split-flap concourse board): a value changes inside its cell; layout never
  reflows when data loads, so the eye learns where "Percentile" lives.
- **Reasons hang in the margin** (donated by the centre-rail reference page): an Unavailable value keeps its cell and a bracketed
  reason sits beside it in the annotation column. The reason is never a tooltip.
- **Print, not dashboard:** ruled sections, one-pixel rules, no card containers, no shadows, radius 0 (2px on controls only).
  The ground is cool tracing-paper white, the ink blue-black, so it reads like the paperwork the user already files.
- **Refused:** purple gradients, glass, shadcn/Tailwind defaults, rows of identical cards, hero-number tiles, sparklines and
  progress rings, icon tiles above headings, decorative animation, eyebrow labels, gradient text.
- **Scene sentence (light, not dark by default):** desk, evening, lamp and room light on, reading dense figures like a statement.
  Dark tokens are defined but are a user preference, not the default.

## 3. Typography, colour, tokens
- **Type:** one family, **Source Sans 3** (variable, self-hosted; carries the rupee sign and OpenType `tnum`). Numbers use
  `font-variant-numeric: tabular-nums lining-nums` everywhere, right-aligned in columns. Status codes are 12px uppercase 600
  weight with 0.08em tracking in the same family (no monospace costume). Scale ratio 1.2, fixed rem (product UI, not fluid).
- **Colour strategy: Restrained.** Neutrals plus one meaning pair. **Ahead of alternatives = deep blue, behind = burnt orange**
  (colour-vision safe, and deliberately not market red/green). Colour is never the only carrier: every figure has its sign
  (+ or −, the server's `display` text), a word ("ahead" / "behind"), and a drawn mark. Unavailable uses diagonal hatching and
  the word, never a tint.
- **Semantic tokens** (CSS variables, one file, light default; dark overrides the same names):
```
--paper:#f2f5f6  --paper-2:#e7ecee  --ink:#13202b  --ink-2:#44545f  --ink-3:#556570  --rule:#c3cdd3  --rule-ink:#13202b
--ahead:#12508f  --ahead-wash:#dce8f4  --behind:#a1440b  --behind-wash:#f6e4d6  --hold:#7a5600  --hold-wash:#f5e8c0
--focus:#13202b (2px ring + 2px --paper gap)   --hatch: repeating-linear-gradient(135deg, var(--rule) 0 1px, transparent 1px 6px)
--font:"Source Sans 3",system-ui,sans-serif   --t-xs:.75rem --t-sm:.8125rem --t-md:.9375rem --t-lg:1.125rem --t-xl:1.375rem --t-2xl:1.75rem --t-3xl:2.125rem
--s-1:4px --s-2:8px --s-3:12px --s-4:16px --s-5:24px --s-6:32px --s-7:48px --s-8:64px   --r-0:0  --r-ctl:2px
--ease:cubic-bezier(.2,.8,.2,1)  --d-fast:120ms  --d-base:200ms
```
- Contrast on `--paper` (computed): ink 15.1, ink-2 7.2, ink-3 5.5, ahead 7.5, behind 5.7; hold on its wash 5.4; ink-3 on paper-2 5.1. All AA.

## 4. Layout and screens
Desktop-first: fixed left rail (Holdings, Trips, Costs, Ask, Upload), content column max 1180px, a 280px annotation margin on
the right where caveats and reasons hang. At <=900px the margin folds under its row; at <=640px tables become labelled
definition rows. Every screen opens with the **chart header**: `Chart prepared 30 Nov 2026 · latest bar 30 Nov 2026` (server's
`latest_sealed_as_of` and `last_bar_date`), and "Data after this date is not used." A date picker changes it; today is never offered.
- **Holdings:** ruled table: Name, Quantity, Avg price, Invested, Market value, P&L, each with its `*_display`. When valuation is
  PARTIAL the total row reads `₹1,205.00 (partial: 1 of 2 holdings valued)` in the `--hold` colour with a hatched cell for the
  missing holding; the sentence is the server's string, never composed by the UI.
- **Trip list:** one row per trip, fixed columns: Listing, Opened, Closed, Return (fees excluded), Alternatives, Percentile,
  Status. Status codes: `EVALUATED`, `NOT EVALUATED` (+ reason), `LISTING EXCLUDED` (+ reason). Gated trips stay in the list.
  Above the table: the sample text ("7 trips · 10 needed") when the server says not enough.
- **Trip detail** (mockup): title with status codes; the one-sentence result; a **histogram** of the ~500 drawn portfolios'
  returns (20 server bins, hand-built SVG) with the trip's own return marked by a dashed line and its bin filled; bins below it
  are tinted "returned less than your trip"; the server's text equivalent sits under the chart. The baseline table (ALT, NIFTY):
  Alternatives' mean, Excess + `direction` word, Percentile (whole %), Portfolios ("500 from 6"), Status, Note; **Alternatives
  picked** (N picked + M left out = the N in the label; left-out rows show ticker + plain reason); **Regime** (volatility band, and
  one sentence when no regime has enough trips); **Across your trips** (interval or the too-few sentence). Alternatives are
  always labelled with the server's text, "Same-sector alternatives (NIFTY BANK, 9)" or "Same-universe alternatives", with the note
  "Same-sector or same-universe alternatives, not a prediction."
- **Behaviour costs:** three rows (Disposition, Chasing, Overtrading): cost, "lower bound" and "fees excluded" notes as the server
  renders them, unknown-fee count; archetype beneath as a status code, or Unavailable + reason; metrics labelled "unitless".
- **Ask the analyst:** a plain form (question, as-of), the answer as prose with citation chips that link to the fact in the other
  screens; labels `Template answer` / `Unverified: showing the raw facts`; a failed call collapses to one line, "Analyst
  offline — your numbers are still here", and every other screen stays interactive.
- **Upload:** file input, the sentence "Upload your oldest tradebook first.", then the result as a ruled summary and the rejected
  rows as a table (line, code, message). `oversell` explains the order rule in plain words.
- **Position of meaning:** primary action is one filled ink button per screen; links are underlined; no icon-only controls.

### Unavailable, partial, too few
- **Unavailable + reason:** the cell shows the hatch and the word `Unavailable`; the reason hangs in the margin as the server's
  plain sentence (`reason_text`): "Nifty 50 membership is not set up, so this comparison cannot be made." Enum codes are never
  shown. Several Unavailable cells in one row collapse into one hatched span. Same weight as a number: not greyed away.
- **Too few trips:** a bordered sentence where the verdict would sit: "Not enough closed trips to say anything yet. 7 trips · 10
  needed". The text is the server's `sample.text` (format `N trips · M needed`). No chart, no interval, no colour. For regimes
  the server sends one sentence: "Not enough trips in any regime yet: Low 3, Normal 9, High 2 (10 needed each)".
- **Partial total:** the `--hold` note above; the missing parts are hatched.
- **Zero is a number:** a genuine `0.00%` renders normally; only `value: null` renders as Unavailable.

## 5. States (every screen)
| State | Treatment |
| --- | --- |
| Loading | Skeleton rows in the real column grid (hatch at 40% alpha), a labelled line "Fetching market data and computing"; controls disabled; no spinner alone. |
| Empty | Teaches the next step: no trades -> Upload; trades but no closed trips -> "Trips appear when a position is fully sold." |
| Error | Distinct for offline backend, 4xx (server `code` + `message`, plain-language map), 5xx; a retry button; the page keeps its other sections. |
| Analyst offline | One line under the question: "Analyst offline — your numbers are still here." Analysis screens never block on it. |
| Not final | 422 `as_of_not_sealed`: "Data for that date isn't final yet." with a button to the latest sealed date. |
| Partial | Explained state, not an error (section 4). |

## 6. Motion and accessibility
- **Motion (purposeful only):** 120ms colour/underline change on hover and focus; 200ms disclosure of a trip row's reason text
  (height + opacity, ease-out); a one-time 200ms position-strip tick settle when a trip opens. Nothing animates on load,
  no number counting, no chart sweeps, no flashing on data change. `prefers-reduced-motion: reduce` removes every transition
  and the tick settle (state changes become instant); motion never carries information.
- **WCAG AA:** text >= 4.5:1, large text and UI marks >= 3:1; tokens are checked in a unit test. Colour is never the only
  signal (section 3). Real landmarks (`nav`, `main`, `aside` for the margin), one `h1` per screen, tables with `th scope`, the
  histogram has `role="img"`, a per-bar `<title>` and the server's visible text equivalent, focus ring always visible (2px + gap).
- **Keyboard:** Tab order follows reading order; `g` then `h/t/c/a/u` jumps to a screen (can be disabled; never the only path);
  arrow keys move between trip rows, Enter opens, Esc returns to the list; the as-of picker is a native `input[type=date]`.
  Skip link to `main`. Touch targets >= 44px on the phone fallback.

## 7. Stack recommendation
Accept the default: **Vite + React 18 + TypeScript**, with these reasons and additions:
- **Types from `/openapi.json` via `openapi-typescript`** (a script, checked in). 013a added response models and the
  `*_display` siblings to OpenAPI, so the compiler enforces "render `display`, never `value`". Regenerate in CI and fail on diff.
- **TanStack Query** for server state: the backend caches per ledger version, so Query's `staleTime` can be long and its
  invalidation can follow an import. One query key per `(endpoint, as_of)`; no client store beyond that.
- **React Router** (data router) for screens and `?as_of=` as URL state, so any view is linkable and printable.
- **Plain CSS with the token file** (cascade layers: tokens, base, components). Tailwind and shadcn are rejected: they ship the
  look this design refuses and add class noise to a small, token-driven UI.
- **Charts: hand-built SVG.** Only three marks exist (portfolio histogram, volatility band, bias cost bar); each is under 60 lines and
  gets exact hatching, text equivalents and no library animation. Reconsider only if a time-series view is added.
- **Fonts self-hosted** (`@fontsource-variable/source-sans-3`) so the app works offline and loads no third party.
- **Dev proxy** in `vite.config.ts` forwards `/api`, `/portfolio`, `/trades`, `/imports`, `/health` to the backend, so no CORS config.
- **Tests:** vitest + Testing Library; fixtures are recorded 013a responses served by MSW (spec A7: no backend, no network).
  A lint rule and a test forbid `toFixed`, `Intl.NumberFormat`, `parseFloat` and arithmetic on response `value`s (spec A1);
  geometry for the histogram and band reads `value` only to place a mark, never to print.
- **Playwright** for one smoke path (upload, trip detail, Unavailable renders the word) against the mocked API.

## 8. Decisions to confirm
1. Blue/orange instead of red/green for ahead/behind (finance convention vs calm, colour-blind safe). 2. Light by default,
dark as a preference. 3. Right-hand annotation margin on desktop. 4. Source Sans 3 as the single family.
5. Keyboard `g`-chords as optional.
6. **Review changes applied (013a.1, built):** server `reason_text` beside every reason; sample text `N trips · M needed`; whole-number
percentiles; `excess_direction`; null counts for Unavailable outcomes; ticker + reason for left-out alternatives; histogram bins
(one `quant/` field retained: the drawn portfolio returns); no "server's own text" footer in the product.
7. **Phone tables** are compact two-line rows (title + status/value, then one line of figures), never a label per field.
8. The hatch for Unavailable is a meaning marker, not decoration (the design detector flags repeating gradients as advisory).
