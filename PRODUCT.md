# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Recommended in `docs/design/013-frontend-design.md` (Vite + React + TypeScript); the owner's stated default, not yet scaffolded.

## Users
A retail Indian investor (NSE/BSE equities and ETFs, INR) reviewing their own past trades, mostly at a desktop in a
deliberate evening or weekend session. Confirmed 2026-10-18: desktop first, phone a readable fallback, English only.

## Product Purpose
Tell the investor whether each of their decisions looks like skill or luck, measure the cost of their behaviour, and
prove no hindsight was used. Every number comes from deterministic backend code; AI only explains. Educational, not
financial advice; no profitability claims, no BUY/SELL wording.

## Positioning
Honest by construction: values the data cannot support are shown as "Unavailable" with the reason, never as 0; small
samples say "X of N trips needed"; luck results are labelled heuristic; alternatives are same-sector or same-universe,
never predictions.

## Operating Context
Single local user. Tradebooks are uploaded oldest first. Analysis runs for a sealed as-of day (yesterday IST at the latest).
The backend formats every number; the frontend renders `display` strings and never formats or computes.

## Capabilities and Constraints
Specs: `docs/specs/013-frontend.md`, `docs/specs/013a-analysis-read-api.md`. Screens: upload, holdings, trip list, trip
detail (luck test, regime split, alternatives), behaviour costs, ask-the-analyst. WCAG AA. No manual trade entry.

## Brand Commitments
The feeling to leave: "honest, calm, nothing hidden". Never casino, never hype.

## Evidence on Hand
None beyond the repository specs; no logo, brand colours, or testimonials exist.
