# Report: NSE/BSE fungibility bug and the follow-ups (2026-10-19)

## Verdict
Fixed where I could reproduce it. Backend: 2518 passed, 0 failed, 0 skipped (live PostgreSQL 16.15 + pgvector + Ollama,
throwaway cluster, removed afterwards; the SQLite-only run is 2428 passed, 90 skipped, those 90 need the live services).
Frontend: vitest 137 passed, lint, typecheck, build and Playwright (10) green.

## 1. Reproduction (tests first)
Synthetic: buy 10 NSE, buy 10 BSE, sell 20 BSE, one ISIN.
- Import: accepted all 3 rows, 0 rejected. Holdings (service and `GET /portfolio/holdings`): 0 held. Separate files in any order,
  BSE symbol differing from the NSE symbol: also 0. **I could not reproduce "20 still held" at import or holdings.** Those layers
  were already ISIN-keyed (feature 002). `tests/test_cross_listing.py` and `test_api_imports.py` now pin that.
- Reproduced in the analysis layer (`tests/test_cross_listing_analysis.py`): trips counted 0 of 14, because positions were
  folded per listing, so the BSE sell of 20 looked like an oversell. If your screen showed 20 held, the likeliest cause is a
  rejected row in your real file (see 3); I cannot confirm without the file. Re-import after the reset (7) and check Upload > Previous uploads.

## 2. Everything that keyed on listing instead of ISIN
Fixed (now `HoldingKey.of(isin, symbol, exchange)`, via `position_key`):
- `quant/bias_cost/cost_basis.py` fold: states, sell-day realised/paper, round trips. A trip is priced by its opening buy's listing.
- `quant/bias_cost/calculations.py`: late-loser index uses the opening listing (`SellEvent.open_instrument`).
- `quant/bias_cost/validation.py`: an excluded or unseriesed listing now takes its ISIN siblings with it (else a false oversell).
- `quant/regime_split/trips.py`: a trip must stay on one position, not one listing.
- `services/portfolio_analysis.py`: `count_round_trips` / `list_round_trips` grouping, excluded-trip counts (each trip once, under
  its opening listing), and a BSE listing priced by its NSE proxy now inherits that listing's corporate-action status.
Already ISIN-keyed, unchanged: import oversell, ledger oversell/correction, holdings fold, quote candidates (NSE then BSE).
Deliberately still per listing: price series and the BSE->NSE proxy; dedupe key `(broker, exchange, broker_trade_id)`;
legacy NULL-ISIN rows (separate, flagged). Luck/regime read `trip.instrument`, which is the opening listing, same prices via the proxy.

## 3. Rejected rows never silent
New `GET /imports/status`; `ImportResultOut.rejected_text`. Holdings, Trips list/detail and Costs show
"N rows were rejected at import; figures may be wrong" with a link to Upload > Previous uploads (`/upload#previous`).
Rejected rows are not stored, only counted, so the row-by-row list exists only right after an upload. A re-upload of the same
file replaces that file's earlier count (the retry); other files' rejections always count.

## 4. Incomplete cost basis
`ValuedHolding.unrealized_pnl` is None when cost basis is incomplete, with the reason; the total is None too. The chip comes from
the new `status_label` (COMPLETE only if priced AND cost basis complete, else PARTIAL) with `status_text`. Note: every imported
holding has unknown charges, so P&L is Unavailable for all imported holdings until fees are known. That is your rule, applied.

## 5-6. Stale data and small items
- Failed refresh with data on screen: "Couldn't refresh. Showing figures from HH:MM" (India time) on Holdings, Trips, trip detail, Costs.
- No status line at 0 holdings. True minus (U+2212) in all displays; the analyst number guard reads it as a minus, so a dropped sign
  is still caught. "X of N" is server text (`rejected_text`, `status_text`). Explicit table/row/cell/columnheader/rowheader roles on every table.

## 7. Reset (dev only)
`python scripts/reset_ledger.py` (dry run), `--yes` to delete. Local database only, one user, README section added.

## Tests I changed (you asked me never to weaken approved tests): please review
- `test_bias_cost_audit`: "same ISIN on two listings is never merged" asserted the old behaviour; now asserts one position, plus a new
  test that NULL-ISIN listings are still never merged. Direct consequence of your instruction.
- `test_regime_split_analysis/contract`: AMBIGUOUS_ISIN can no longer come out of the fold (mixed ISINs are now separate positions);
  the guard stays and is tested on a hand-built trip; the analysis-level test now asserts the mixed pair forms no trip.
- Display tests: hyphen to U+2212. `test_api_summary`, `test_api_imports`: additive response keys. `test_import_batch_repository`: added read-only `list_for_user`.
- Regenerated `docs/demo/alterfolio-demo.html` (minus sign) and the frontend fixtures; spec 006 line updated.

## Not done / caveats
- Mixed-calendar edge: a position whose NSE and BSE series differ would use the opening listing's calendar; with the proxy they are identical.
- Real-data verification not possible here (I did not read your files). Please re-import after the reset and tell me what Previous uploads shows.
