# Feature 016: order-independent import (SPEC, awaiting owner review, no code yet)

Status: proposed 2026-10-19. Replaces the "upload your oldest tradebook first" rule. Supersedes parts of 002 (oversell and
quarantine at import) and the import-order wording in 013. Owner decisions needed are in section 12.

## 1. Problem
Import replays the user's whole ledger in trade-time order and rejects a sell that exceeds the position at that moment
(`oversell`, then `after_oversell` for the rest of that ISIN). A real user uploaded the newer tradebook first: a valid sell was
rejected permanently (rejected rows are not stored), and holdings then showed shares the user does not own. The rule is a trap:
the ledger's truth must not depend on file order. Principle: **store every valid trade; judge order only when reading.**

## 2. Design in one paragraph
Import becomes parse -> validate each row alone -> dedupe -> store. There is no oversell check at import and no quarantine.
Holdings, realized P&L and every analysis already derive from the stored trades at read time (nothing derived is stored), so the
"rebuild after every import" is a deterministic fold that runs on read and tolerates a sell larger than the known position.
Nothing is migrated except two coverage columns (section 7).

## 3. What is stored (FR-1)
- Every row that passes row-level validation is stored, whatever order or file it arrives in.
- Dedupe key unchanged: `(user_id, broker, exchange, broker_trade_id)`, original rows only. Same key and identical values =
  duplicate (counted, not stored). Same key with different values = rejected `conflict` as today. Never dedupe on `order_id`.
- Re-uploading the same file is idempotent: 0 rows stored, all counted duplicates, ledger and caches unchanged (a new batch row is
  still written, as today, and carries coverage).
- Result fields `quarantined_isins` and the codes `oversell` / `after_oversell` are removed. A new count `unmatched_sells` says how
  many stored sells exceed the position known at their moment (informational, not a rejection).

## 4. Deterministic order (FR-2)
The fold order is a pure function of trade content, never of upload order, `recorded_at` or random row ids:
1. `trade_timestamp` (UTC instant; it already combines trade date and execution time, IST at the source).
2. BUY before SELL at the same instant (existing rule; a same-second buy and sell are treated as buy first. Open question 12.4).
3. `exchange` (value text), then `int(broker_trade_id)` (numeric, as `_canonical_key` does today).
4. Manual rows (no broker trade id) sort after imported rows at the same instant, by `recorded_at`, then `id`.
Same-day rule: there is no day-level grouping; two trades the same day are ordered by rule 1 first. Only an exact timestamp tie
reaches rules 2-4. Today's `canonical_order` uses `recorded_at, id` before any content tiebreak, which is upload-order dependent;
016 replaces it. This is the single behavioural change to the fold's ordering and needs a regression test on the old fixtures.

## 5. Unmatched sells (FR-3, FR-4)
Fold per position key (ISIN, else (symbol, exchange); unchanged from the 2026-10-19 fix). For a sell of `q` with `h` held:
- `q <= h`: as today (weighted-average cost, realized P&L).
- `q > h`: **matched = h, unmatched = q - h.** The position becomes 0, never negative. The matched part behaves as today. The
  unmatched part has **cost basis unknown**: no cost, no P&L, no guess, no assumed price or date.
- A later buy never retroactively funds an earlier unmatched sell (it was not yet bought). Only an older upload can resolve it.
Holdings: quantity is `max(0, ...)` by construction; a holding never goes negative; an unmatched sell never reduces another ISIN.
The flag lives on realized P&L, not on the holding (the position is 0 right after an unmatched sell): `realized_pnl` is
Unavailable with the reason when any sell in it is (partly) unmatched; a matched-only figure is never shown as the whole.
Analyses (006-008): the current `cost_basis` rule "sell above held quantity is an input error" and "sell with no earlier buy is
excluded" both become one outcome: the trip containing an unmatched quantity is **not evaluated** and carries
`unmatched_quantity` (Decimal) and `unmatched_since` (date) in its read type.
- Trip return, luck, regime label inputs: Unavailable, reason text e.g. "The buy for 10 shares is not in your uploaded tradebooks
  (before 17 Nov 2025)." The date is the start of the coverage range containing the sell (section 7). Never a guessed cost.
- A trip fully matched is unaffected, even if the same ISIN has an unmatched trip elsewhere.
- Aggregate bias metrics (disposition, chasing, overtrading): computed from fully matched trades only, and carry a visible note
  "excludes N trips with unknown cost" using the existing lower-bound note mechanism. Open question 12.1 (alternative: Unavailable).
- Reason texts live in `domain/display.py` (`reason_text`), as every other reason does.

## 6. Resolution on a later upload (FR-5)
Because nothing derived is stored, uploading the missing older file adds rows; the next read folds the full set, the buy now
precedes the sell, the unmatched quantity becomes 0 and the trip is evaluated. No manual step, no re-import of the newer file.
Property: for any set of files, the stored rows, holdings and analysis equal those of one upload of the merged set.

## 7. Coverage (FR-6)
- Each batch records `covered_from` and `covered_to`: the first and last trade date (IST) among ALL parsed valid rows in the file,
  duplicates included (a re-upload still proves coverage). Two nullable DATE columns on `import_batches`; the migration
  backfills existing batches from their trades' min/max and leaves batches with no rows NULL. This is the only schema change.
- Coverage = union of batch ranges; ranges that overlap or touch (next day) merge. A **gap** is the span between two merged ranges
  ("No tradebook covers 6 Nov 2024 - 2 Oct 2025"). Before the first range is not a gap (nothing is known to be missing there),
  but unmatched sells point at it through the "before <date>" reason.
- Limit, stated plainly to the user: a file reveals only its first and last trade, not the period the broker was asked for. A quiet
  stretch with no trades looks like a gap. The wording is "No uploaded tradebook has trades dated between X and Y", and it is a
  warning ("figures that depend on those dates may be incomplete"), not an error. Open question 12.2 (let the user declare periods).
- API: `GET /imports/status` (exists) gains `coverage: [{from, to, from_display, to_display}]`, `gaps: [{...}]`, `gap_text`
  (server-built sentences). Gaps ignore dates after the viewed as-of.
- UI: Upload shows coverage and gaps under Previous uploads; Trips and Holdings show a warning beside the existing rejected-rows
  warning when `gaps` is non-empty, linking to `/upload#previous`. Frontend renders server strings only.

## 8. What stays rejected (FR-7)
Only rows that are wrong on their own: bad or missing ISIN shape, non-positive or malformed quantity or price, invalid side, bad
timestamp or `date_mismatch`, numeric limits, NUL, over-length text, row/size caps, `conflict` (same key, different values). Shown
as today (line, code, message; first 200 listed, exact total, `rejected_text`). File-level failures stay 422 `invalid_import_file`.
The 2026-10-19 rejected-rows warning on Holdings/Trips keeps working and now only means malformed rows.

## 9. Copy and docs to change (FR-8)
Remove "oldest first" from: `PRODUCT.md:27`; `README.md` reset paragraph; `docs/specs/013-frontend.md` lines 8 and 46;
`frontend/src/features/upload/UploadScreen.tsx` (lede, `OversellNote`, quarantine list); `frontend/src/shared/api/errors.ts`
(`oversell` copy); matching UI and e2e tests; `CLAUDE.md` section 10 first bullet and the ledger-model oversell wording;
`docs/specs/002-*` import sections (mark superseded). The trips-table caption "oldest first" is a sort order and stays. New upload
lede: "Upload your tradebooks in any order. Anything that cannot be matched yet is kept and flagged."

## 10. No hindsight (FR-9)
Unchanged mechanism: a result for as-of D uses only trades with `trade_timestamp <=` the D boundary; the fold, unmatched
quantities and trip statuses are computed from that cut only. A buy dated before D that was uploaded after D is included today
(disclosed via `late_recorded_row_count`) and stays so. Coverage gaps and the "before <date>" text use only dates <= D. Test:
adding trades dated after D never changes any D result (existing point-in-time test, extended to unmatched sells).

## 11. Performance and cache
- Import today replays history per inserted row (`find_oversell` over the ISIN's whole history, roughly O(n^2) per ISIN). 016 removes
  that: parse, one key lookup per row, bulk insert. Import cost becomes O(rows) plus the dedupe lookups.
- Read cost: one sort plus one pass, O(n log n). For 5,000 rows per file and tens of thousands of trades this is milliseconds to
  tens of milliseconds in Python; the plan must measure it (budget: fold under 100 ms for 10,000 trades) before claiming it.
- Cache: `AnalysisReadService` is keyed `(user, as_of, ledger_version)`, `ledger_version = (row count, max recorded_at)`. Any import
  that stores a row changes it. An import that stores no rows (idempotent re-upload) leaves it unchanged, correctly, but may
  change coverage. So the key gains `coverage_version = (batch count, max created_at)`. No TTL stays; no explicit invalidation call.
- Concurrency: the per-user lock around import stays (it guards the dedupe-key race and batch creation), but is held for a
  shorter time.

## 12. Tests to write (FR-10), all synthetic
1. Property test: for random trade sets over several ISINs and both exchanges, split into 2-4 files, every permutation of upload
   order (and a random re-split) gives identical stored trades (by content), holdings, realized P&L, trips and analysis facts and
   fingerprints. Includes same-instant ties and duplicates across files.
2. Owner repro: buy 10 NSE, buy 10 BSE, sell 20 BSE, newest file first -> 0 held, 0 unmatched, through the service and the routes.
3. Unmatched: sell 20 with 10 held -> position 0, never negative, matched 10, unmatched 10, trip not evaluated, reason text with
   the date; no cost or P&L number anywhere; sell with no buys at all; unmatched in one ISIN leaves another ISIN untouched.
4. Resolution: upload the newer file, then the older one -> identical to the merged single upload.
5. Idempotence: the same file twice -> 0 new rows, identical ledger and `ledger_version`; changed values under one key -> `conflict`.
6. Ordering regression: the old canonical order versus the new one on existing fixtures; no result depends on `recorded_at`.
7. Coverage: ranges merge when overlapping or touching; gap text; gaps after as-of ignored; backfill migration (SQLite and live PG).
8. Rejections: each malformed class still rejected with the same code; oversell codes no longer produced.
9. No-hindsight and isolation: future trades never change a past result; two users never see each other's coverage or trades.
10. UI: no "oldest first" string remains (grep test); gap warning on Trips and Holdings; unmatched reason shown; vitest and e2e.
11. Performance guard: fold of 10,000 synthetic trades under the budget; import of 5,000 rows without per-row history replay.

## 13. Out of scope and open questions
Out of scope: corporate actions (splits, bonuses); inferring a missing buy's price or date; shorting (ledger stays long-only);
auto-recovering rows already rejected by the old rules (re-import the original files after the reset); other brokers; changing
the 5,000-row and 2 MiB caps; persisting analysis results.

Open questions for the owner:
1. Aggregate bias with unmatched trips: show the figure for matched trips with an "excludes N trips" note (recommended), or make
   the whole metric Unavailable?
2. Coverage from first/last trade only (recommended, nothing to type) or let the user declare the period they exported, which makes
   gaps exact but adds input?
3. Manual `POST /trades` sells and corrections/voids: keep today's strict oversell rejection (recommended: a typed trade is a
   deliberate act) or allow unmatched there too?
4. Same-instant buy and sell: buy first (recommended, matches today) or treat as unordered and flag?
5. Realized P&L on a partly matched sell: Unavailable for that sell (recommended) or show the matched part labelled partial?
6. Past batches have no stored rejections: is a note on Upload ("rows rejected by the old rule are not recoverable, re-import")
   enough, or do you want the reset script to be offered in the UI copy?
