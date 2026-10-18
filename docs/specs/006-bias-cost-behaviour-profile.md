# Feature 006: Bias Cost & Behaviour Profile

Status: owner-approved 2026-10-14. Formula version `bias-v1` is a heuristic, not an empirically calibrated model.
Plan: `docs/plans/006-bias-cost-behaviour-profile.md`. Package: `backend/app/quant/bias_cost/`.

## 1. Objective
Measure disposition effect, chasing and overtrading from effective ledger trades as signed INR costs, plus a deterministic
rule-based archetype. Observations only: never BUY/SELL, no clustering, no AI numbers.

## 2. Inputs and outputs
- In: `LedgerTrade` (internal `trades.id`, `Instrument(symbol, exchange)`, optional ISIN, side, qty, price, UTC time,
  `ChargeValue` known/unknown), `MarketSeries` per listing, `BiasParameters`, optional set of listings with known corporate actions.
- Out: three `BiasResult` (one per bias) and a `BehaviourProfile | Unavailable`, all frozen and schema-versioned. Each metric has
  `cost_inr` (exact Decimal) or `Unavailable(reason)`, `gross_cost_inr`, `fees_known`, `fee_status`, `unknown_fee_trade_count`,
  `details`, exclusions, listing provenance (symbol, exchange, series fingerprint) and its own input fingerprint.
- Fingerprints hash the complete trade record (incl. ISIN, even if no formula uses it); an ISIN-only change alters them.
- Money is exact Decimal; `present_inr` (half-even, 6 places) is the only rounding, applied at presentation, never stored. Derived values (averages, ratios, products of them) use a fixed 60-digit half-even context.

## 3. Decisions (owner, 2026-10-14)
- Listing: use each trade's own exchange; never fall back NSE/BSE. Position identity is the ISIN when a trade has one (NSE and BSE listings of one ISIN are ONE position, changed 2026-10-19 after a real-data bug; a round trip is priced by the listing of its opening buy), else the legacy (symbol, exchange); NULL-ISIN rows are never merged into an ISIN position.
- Strict completeness (owner, final): a listing WITH trades but no series makes every metric and the profile `Unavailable`; a
  series for a listing with no trades is ignored. Why: each metric pools all listings (paper positions, chasing baseline,
  session counts), so dropping one would silently change what the number means. Traded listings are never silently excluded.
- Sign: positive = the behaviour cost money, negative = it helped. No clamping, no absolute value.
- Fees: `COMPLETE` / `PARTIAL` / `UNKNOWN`; unknown fees are counted, never summed, never 0; a result with unknown fees is a lower bound.
- Accounting: weighted-average cost as in `services/holdings.py`, price-only (fees excluded) for gross P&L.
- H (owner, final): observation unit = each fully closed round trip with gross P&L > 0, counted once (open buy session to
  final closing sell session); partial sells never count. PGR/PLR keep their own (listing, sell day) unit. Integer sessions sorted ascending; odd count => middle value; even count => the LOWER
  of the two middle values (never averaged). Costs consider losing sells held longer than H.
- Fewer than 10 eligible closed round trips => `Unavailable("insufficient history")`.

## 4. Formula rules (all `bias-v1`)
Position = one listing. Round trip = flat -> open -> flat on one listing; open session = first buy, close session = last sell.
Sessions are bar indexes in that listing's series (no calendar, gaps are never filled). Gross P&L of a sell =
`qty * (price - avg_cost)`; of a round trip = sum over its sells. Notional = `quantity * ledger price`.
- Disposition (Odean): per (listing, sell day) sum realised P&L: gain, loss or zero. Paper positions = listings held at the end
  of that day and not sold that day, valued at that day's close vs average cost. `PGR = RG/(RG+PG)`, `PLR = RL/(RL+PL)` summed
  over sell days; zero-P&L counted and excluded; `PGR-PLR` is reported (undefined if a denominator is 0). H = lower median of
  winning closed round trips' holding sessions (see section 3). Cost = sum over losing sells held > H of `(close at open+H sessions - exit price) * qty`.
  Unavailable if no winning sell. Close is split-adjusted, ledger price is raw: listings with known corporate actions are excluded.
- Chasing: buy at bar index i is a chase if `close[i-1] >= close[i-21] * 1.10` (prior 20 sessions, buy session excluded; needs
  i >= 21). Forward return = `close[i+20]/close[i] - 1`. `cost = sum over chase buys of notional * (mean non-chase forward
  return - chase forward return)`. Unavailable with no non-chase buy having forward history. Overlapping forward windows are
  not de-duplicated; the baseline mean is unweighted while the cost is notional-weighted (documented limitation).
- Overtrading: short-term = closed round trip with `close index - open index <= 5`. Per trip
  `gross = max(0, -gross_pnl)`, `fees = known fees+taxes of all its trades`; cost = sum(gross) + sum(known fees). One-sided by
  the owner's formula: profitable short trips add only their fees. Fees are added once, only here.
- Archetype, first match: CHURNER if short-term trips / eligible closed trips >= 0.30; CHASER if chases / eligible buys
  (i >= 21) >= 0.40; DISPOSITION_PRONE if `PGR-PLR >= 0.10`; else DISCIPLINED. If a rule's metric is unavailable and no earlier
  rule matched, the profile is `Unavailable` (never treated as 0).

## 5. Invariants and errors
- `BiasInputError`: malformed trade, duplicate id, equal (time, id) tie, timestamp outside the window, non-INR, series/listing
  mismatch, unapproved `formula_version`, oversell within a listing that has earlier buys.
- A sell on a listing with no earlier buy in the supplied trades is excluded as opened before the window (recorded).
- A listing whose trade has no bar on its session date is excluded with a reason; no data is invented.
- Disposition/chasing use no bar after the sell session / buy session, except chasing's 20-session forward outcome.
- No float, clock, randomness or `quant/backtest` import; quant imports only stdlib, `app.domain`, `app.quant.market_data`.

## 6. Acceptance tests
1. Listing isolation: NSE and BSE of one ISIN stay separate; missing series => `Unavailable`; provenance lists each used listing.
2. Signed costs: positive (underperformance, price fell after H) and negative cases; never clamped.
3. Fees: COMPLETE, PARTIAL (lower bound), UNKNOWN (`fees_known` None); unknown never 0; fees counted once.
4. PGR/PLR fixture with paper gains/losses, zero-P&L exclusions, zero denominators, lower-median H, disposition cost fixture.
5. Chasing at +10.0% vs +9.99%, i = 20 vs 21, forward history short, no non-chase buys, no chases (cost 0).
6. Overtrading at 5 vs 6 sessions, profit vs loss gross P&L, fees only for short trips.
7. Archetype thresholds (0.30, 0.40, 0.10), precedence, denominators, 9 vs 10 trips, unavailable metrics.
8. Per-metric fingerprints differ and change with relevant inputs only; permutation-stable; frozen results.
9. Future leakage: bars after the allowed limit cannot change a result; oversell error; pre-window sell excluded.
10. Import boundary, float-ban, Decimal-money and no-clock scans.

## 7. Out of scope
Corporate-action normalisation or detection, tax, fee estimation, pre-window history, clustering/ML, AI, API, UI, persistence,
a trading calendar, and moving or merging ISIN holdings across listings.
