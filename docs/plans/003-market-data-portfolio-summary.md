# Feature 003 — Market Data Port + Portfolio Summary (plan)

## Context
FR-8 (portfolio summary + valuation status) and FR-9 (quotes via a provider abstraction, NSE/BSE handling) are the
last stage-1 pieces. `docs/spec.md:53,54,63,74,89,90` define them only thinly (no unrealized P&L, no stale rule, no
as_of, no listing choice, no error codes). This plan settles every open item, builds on `fold_holdings` unchanged,
and adds no persistence. Nothing implemented yet. First implementation step: copy this plan to
`docs/plans/003-market-data-portfolio-summary.md` (repo rule: plan file before code, <200 lines).

## Decisions (the 16 required)
1. **FR-8/FR-9 contract.** `GET /portfolio/summary` returns total trades, total invested, per-holding rollup, valuation
   status. Quotes come from a `MarketDataProvider` port. Additions beyond spec.md (market value, unrealized P&L,
   quote status) are user decision **U11** (record in `docs/v1-lineage.md`).
2. **Instrument identity.** Lookup key = `Instrument(symbol, exchange)` (a listing). ISIN is never sent to Yahoo (no
   ISIN lookup); it stays the holding identity. ISIN holding -> candidate listings from `Holding.listings`, tried in
   order **NSE, then BSE**. NULL-ISIN legacy holding -> its single listing only. A listing is never replaced by a
   different symbol; the quote records the exchange/symbol actually used. No NSE<->BSE merging beyond that ordered
   fallback within one ISIN.
3. **Quote model** `MarketQuote(instrument, price: Decimal, currency, price_timestamp, retrieved_at, source)`;
   frozen, in `app/providers/market/port.py`. Price must satisfy `0 < price < MAX_AMOUNT`; currency must be INR.
4. **Timestamps.** `price_timestamp` = provider's last-trade time (epoch -> tz-aware UTC). `retrieved_at` = injected
   clock at fetch. Naive/missing provider time => `INVALID`. Never substitute retrieved_at for price_timestamp.
5. **Current vs historical.** Current-only. `as_of` query param is declared and rejected: 422
   `historical_valuation_unsupported`. Response carries `basis: "CURRENT"` and `valuation_time` (clock). Holdings fold
   runs with `as_of=None` (unchanged). `GET /portfolio/holdings?as_of=` unchanged.
6. **Missing/stale.** Valuation price = Yahoo `regularMarketPrice` (last trade; when market is closed this is the last
   close and is valid). Stale = `retrieved_at - price_timestamp > quote_stale_after` (setting, default 7 days, covers
   weekends/holidays). Stale, missing, invalid, or errored quotes are **not valued** and never estimated.
7. **Provider errors.** Port returns per-instrument `QuoteOutcome = MarketQuote | QuoteFailure(kind, detail)`;
   kinds `NOT_FOUND | PROVIDER_ERROR | INVALID_RESPONSE`. Port never raises for per-instrument problems; a whole-
   provider failure (timeout, 429, 5xx, network) yields `PROVIDER_ERROR` for every instrument. Provider failure is
   distinguishable from "no such quote". HTTP status stays 200; failure shown in `quote_status`.
8. **Yahoo adapter.** `app/providers/market/yahoo.py`, `httpx` direct to the public chart endpoint (unofficial, may
   change: documented risk). Suffix `.NS` (NSE), `.BO` (BSE). Parse with `json.loads(parse_float=Decimal)` so no float
   ever exists. `httpx` moves from dev extra to runtime in `pyproject.toml` (already pinned in `constraints.txt`
   0.28.1; verify, regenerate only if the closure changes). Timeout 3s/request, 20s total budget, sequential
   `httpx.Client`; remaining instruments after budget => `PROVIDER_ERROR(timeout)`. Max 200 distinct listings per call.
9. **Caching/persistence.** None. Fetch per request (matches `design.md:81,158`). No tables, **no migration**.
   Summary never stored (`design.md:80`).
10. **Summary response** (all money fields `DecimalOut` strings, 6 dp, existing `money_str`):
    `schema_version:1, basis, valuation_time, valuation_status, total_trades, holdings_count, valued_holdings_count,
    total_invested, total_market_value|null, total_unrealized_pnl|null, cost_basis_complete, holdings[]`.
    Holding = existing `HoldingOut` fields + `quote_status, quote{symbol,exchange,price,currency,price_timestamp,
    retrieved_at,source}|null, market_value|null, unrealized_pnl|null`. Order unchanged (ISIN asc, legacy last).
    `total_market_value`/`total_unrealized_pnl` sum **valued holdings only** and are `null` when UNAVAILABLE; clients
    must read `valuation_status` (PARTIAL totals are explicitly partial). `total_invested` covers all holdings.
    `cost_basis_complete` = all holdings complete; P&L for incomplete holdings is still shown but flagged per holding
    (imported buys have fees 0 => P&L overstated).
11. **Valuation status enum** `COMPLETE | PARTIAL | UNAVAILABLE` (spec.md:53; NOT "FULL"). COMPLETE = every holding
    valued (vacuously true for an empty portfolio: zeros, `[]`, per spec.md:90, totals `"0.000000"`). PARTIAL = >=1 valued
    and >=1 not. UNAVAILABLE = holdings exist, none valued. Per-holding `quote_status`:
    `VALUED | STALE | NOT_FOUND | PROVIDER_ERROR | INVALID`.
12. **Route/status.** `GET /portfolio/summary[?as_of]`. 200 always incl. provider failure and empty portfolio; 422
    `historical_valuation_unsupported` / naive `as_of` (existing `invalid_trade` style envelope
    `{"detail":{"code","message"}}`). No existing contract changes.
13. **Decimal/rounding.** `market_value = qty * price` via `MONEY_CONTEXT`; `pnl = market_value - invested_amount`;
    totals summed exactly; quantize to 6 dp once at the API boundary (D5). Market value >= `MAX_AMOUNT` => holding
    `INVALID` (reject, never round/cap). No float anywhere in providers/ or services/.
14. **Migrations.** None.
15. **Tests** — see matrix.
16. **Conflicts with the pasted spec / authoritative docs** — see below.

## Conflicts / things to know
- Pasted spec asks to treat unrealized P&L as "if explicitly supported": it is not in spec.md/design.md; included
  only because the user approved it (U11).
- Pasted wording "fully/partially valued/unable" vs authoritative enum `COMPLETE/PARTIAL/UNAVAILABLE`: authoritative wins.
- spec.md:74 lists summary input "none"; as_of is explicitly rejected rather than ignored (design.md:144-145).
- Yahoo BSE suffix is `.BO` (not `.BS`). V1 `API.md` cited by FR-8 is stale (`v1-lineage.md:78`); not ported.
- Symbol canonicalization (deferred to 003 by plans 001/002): trim + upper-case + `^[A-Z0-9&_-]{1,64}$` only inside
  the adapter's mapping; ledger symbols stay verbatim. Non-matching => `NOT_FOUND`, never guessed.
- `test_money_paths_do_not_use_float` does not cover `providers/`; extend it (adapter uses `Decimal` parse).
- Yahoo endpoint is unofficial; terms/availability risk accepted by user choice; the port keeps it swappable.
- `total_trades` undefined in spec: defined as effective trades (EXECUTED, not superseded).

## Implementation steps (new/changed files under `backend/`)
1. `app/providers/__init__.py`, `app/providers/market/{__init__,port}.py` — `MarketDataProvider` Protocol
   (`get_quotes(instruments, retrieved_at) -> dict[Instrument, QuoteOutcome]`), `MarketQuote`, `QuoteFailure`.
   stdlib + `app.domain` only.
2. `app/providers/market/yahoo.py` — adapter (httpx only here). Maps Yahoo JSON -> `MarketQuote`; isolates its
   response shape; failures -> `QuoteFailure`.
3. `app/services/portfolio_summary.py` — pure `value_holdings(holdings, outcomes, retrieved_at, stale_after)`
   (listing order, staleness, status, arithmetic) + `PortfolioSummaryService(ledger, provider, clock, stale_after)`
   using `LedgerService.holdings()` and a new `LedgerService.effective_trade_count(user_id)` (reuse
   `repo.list_effective`). Imports `app.providers.market.port` only. `holdings.py` untouched.
4. `app/schemas/summary.py` — `SummaryOut`, `SummaryHoldingOut`, `QuoteOut`; reuse `DecimalOut`, `ListingOut`.
5. `app/api/routes/portfolio.py` add route; `app/api/deps.py` add `get_market_data`, `get_summary_service`;
   `app/api/main.py` `create_app(..., market_data=None)` default `YahooProvider` (built lazily, no network at
   startup), `app.state.market_data`; `app/config.py` add `quote_stale_after_days=7`, `market_timeout_seconds=3`.
   Register `historical_valuation_unsupported` (422).
6. `pyproject.toml` httpx -> runtime; check `constraints.txt`.
7. Docs: plan copy, `docs/specs/003-*.md` + README row, `docs/v1-lineage.md` U11, CLAUDE.md status/context map
   (all <200 lines).

## Test matrix (pytest, offline; fake provider + `httpx.MockTransport` for adapter)
- **Port/adapter:** Protocol contract via fake; Yahoo mapping `.NS/.BO`; JSON->Decimal exactness (e.g. 2450.35, no
  float); epoch->UTC; naive/missing time -> INVALID; 404/empty result -> NOT_FOUND; 429/5xx/timeout/network/bad JSON
  -> PROVIDER_ERROR/INVALID_RESPONSE; non-INR; price <=0; partial batch (some ok, some failed); response fields do
  not leak into `MarketQuote`; budget exhaustion; symbol regex.
- **Valuation (pure):** single valued; multiple; missing; mixed -> PARTIAL; all missing -> UNAVAILABLE; stale ->
  not valued; Decimal exact arithmetic + 6dp quantize once; zero holdings -> COMPLETE zeros; fully exited omitted;
  ISIN holding with NSE+BSE (NSE ok; NSE fail -> BSE used, exchange reported; both fail); NULL-ISIN legacy uses only
  its listing, never ISIN's; two ISINs same symbol different exchange not merged; MAX_AMOUNT overflow -> INVALID;
  provider failure never becomes zero; `cost_basis_complete` flag; point-in-time: future-dated trades/quotes (clock
  fixed) don't change result.
- **API:** 200 shapes, string decimals, ordering, `as_of` -> 422 code, empty portfolio, provider down -> 200
  UNAVAILABLE, user isolation (USER_B trades/quotes never in USER_A summary) at service and route level,
  `create_app()` default builds without network, summary totals consistent with `/portfolio/holdings`.
- **Boundaries (extend `tests/test_import_boundaries.py`):** `providers` may not import api/schemas/repositories/
  models/services; domain/models/repositories/schemas/quant may not import `app.providers`; only `providers/market/
  yahoo.py` imports httpx; services import only `app.providers.market.port`; add `providers` to the no-float test;
  `portfolio_summary` pure part bans sqlalchemy/fastapi/pydantic.
- **Regression:** full 001 + 002 suites unchanged; PG live suite unchanged (no migration; confirm `alembic heads`
  is still `0002`).

## Verification
`cd backend; python -m pytest` (all green, no env file, no network); `alembic heads` = 0002; manual smoke with
fake provider via TestClient; one optional live Yahoo check run by the user (not in CI); `git diff --stat` shows
no changes to holdings/import/trade code beyond the listed files; Markdown files <200 lines.

## Exit gate
Contracts frozen above (route, schema, enum, no persistence). Approved 2026-10-12 and implemented; as-built in `docs/specs/003-market-data-portfolio-summary.md`.
