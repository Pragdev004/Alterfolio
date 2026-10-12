# 003 Market data port and portfolio summary (as built)

Plan: `docs/plans/003-market-data-portfolio-summary.md`. Requirements: FR-8, FR-9 (`docs/spec.md`). No migration, no
persistence, no cache. Holdings, ledger and import behavior are unchanged.

## Layout
- `app/providers/market/port.py`: `MarketDataProvider` Protocol, `MarketQuote`, `QuoteFailure`, `QuoteFailureKind`
  (`NOT_FOUND`, `PROVIDER_ERROR`, `INVALID_RESPONSE`). Stdlib + domain only. The only provider module services import.
- `app/providers/market/yahoo.py`: Yahoo adapter (httpx, unofficial chart endpoint). The only module that imports httpx
  or knows Yahoo's URL/JSON. `create_app(market_data=...)` injects a provider; the default is built lazily, so
  constructing the app never touches the network.
- `app/services/portfolio_summary.py`: pure `value_holdings` plus `PortfolioSummaryService` (reads
  `LedgerService.holdings()` and `effective_trade_count()`, asks the provider, values).
- `app/schemas/summary.py`, `GET /portfolio/summary` in `app/api/routes/portfolio.py`.

## Quote semantics
- Lookup key is the listing `Instrument(symbol, exchange)`; ISIN is never sent to a provider. Yahoo suffixes: NSE `.NS`,
  BSE `.BO`. Adapter canonicalization: trim, upper-case, `^[A-Z0-9&_-]{1,64}$`, else `NOT_FOUND` with no request.
- Valuation price is the last traded price (`regularMarketPrice`); a closed market is valid. `price_timestamp` is the
  provider's last-trade time (UTC); `retrieved_at` is the injected clock. Naive/missing time is invalid.
- A quote needs `0 < price < MAX_AMOUNT`, currency INR, aware timestamp, not later than `retrieved_at` + 5 minutes.
- Stale when `retrieved_at - price_timestamp > ALTERFOLIO_QUOTE_STALE_AFTER_DAYS` (default 7). Stale quotes are not valued.
- Prices are parsed straight to Decimal (`parse_float=Decimal`). Timeout 3 s per request, 20 s total, max 200 listings.
- A provider failure never becomes a price or zero. A provider that raises is treated as `PROVIDER_ERROR` for all.

## Listing choice
An ISIN holding tries its listings NSE first, then BSE, and takes the first usable quote; the quote reports the listing
used. A NULL-ISIN legacy holding uses only its own `(symbol, exchange)`. No other symbol is ever substituted.

## Response (`schema_version` 1, `basis` CURRENT)
`valuation_time`, `valuation_status`, `total_trades` (effective trades), `holdings_count`, `valued_holdings_count`,
`total_invested`, `total_market_value`, `total_unrealized_pnl`, `cost_basis_complete`, `holdings[]`.
A holding is the holdings-route shape plus `quote_status`, `quote`, `market_value`, `unrealized_pnl`.
- `valuation_status`: `COMPLETE` (all holdings valued, also the empty portfolio with zero totals), `PARTIAL` (some),
  `UNAVAILABLE` (holdings exist, none valued; both totals null).
- `quote_status`: `VALUED | STALE | NOT_FOUND | PROVIDER_ERROR | INVALID` (first listing's status when none is valued).
- Totals of market value and P&L sum valued holdings only; `total_invested` covers all. Read `valuation_status`.
- `market_value = quantity * price`; `unrealized_pnl = market_value - invested_amount` (fees included). Imported buys
  have no fees, so P&L is overstated while `cost_basis_complete` is false. A market value >= `MAX_AMOUNT` is `INVALID`.
- Decimals are strings at 6 dp, quantized once at the boundary (`money_str`).

## Errors
200 for provider failure, stale or missing quotes, and an empty portfolio. Any `as_of` query parameter: 422
`historical_valuation_unsupported` (valuation is current-only; no historical price is invented).

## Tests
`test_market_yahoo.py` (adapter via `httpx.MockTransport`), `test_portfolio_summary.py` (pure valuation, service),
`test_api_summary.py` (route, isolation, no network), `test_import_boundaries.py` (provider isolation, no float).
The live Yahoo endpoint is not exercised by any test.
