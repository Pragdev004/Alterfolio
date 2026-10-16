# Feature specs (as built)

One file per delivered feature. These describe what the code does today and how it is verified. They are not plans:
the approved decisions live in `docs/plans/`, the product-level requirements in `docs/spec.md`, the architecture in
`docs/design.md`. If a spec here disagrees with the code, the code and its tests win; fix the spec.

| Spec | Feature | Status |
| --- | --- | --- |
| `001-trade-ledger-holdings.md` | Append-only trade ledger, holdings fold, REST API | Delivered |
| `002-1-tradebook-upload-reader.md` | Streaming multipart reader for the tradebook upload | Delivered (used by the import route) |
| `002-2-tradebook-parser.md` | Pure Zerodha tradebook CSV parser | Delivered (used by the import service) |
| `002-3-import-persistence-foundation.md` | Migration 0002, models, repositories, `HoldingKey` | Delivered (live PostgreSQL unverified) |
| `002-4-import-service.md` | Import service: dedupe, quarantine, oversell, batches, user lock | Delivered (live PostgreSQL unverified) |
| `002-5-api-and-holdings.md` | Import route, ISIN-required manual API, corrections, ISIN-grouped holdings | Delivered (live PostgreSQL unverified) |
| `003-market-data-portfolio-summary.md` | Market-data port, Yahoo adapter, `GET /portfolio/summary` | Delivered (live Yahoo unverified) |
| `004-quant-market-data-foundation.md` | Daily-bar port, Yahoo daily bars, `MarketBar`/`MarketSeries`, market-series service | Delivered, committed as `e7010bc` (live Yahoo unverified) |
| `005-backtesting-foundation.md` | Pure point-in-time daily-bar backtest engine (implementation contract) | Steps 1-6 committed (`acac749`, `55a03de`); awaiting owner review; D7 trial-count gate OPEN — OWNER DECISION |
| `006-bias-cost-behaviour-profile.md` | Bias costs (disposition, chasing, overtrading) in INR and rule-based behaviour archetype | Proposed / awaiting spec review (not implemented) |
| `007-luck-test.md` | Seeded luck test: closed round trips vs similar-alternative and Nifty 50 random portfolios, bootstrap interval | Implemented, awaiting owner review (not committed) |
| `008-regime-split.md` | Per-regime Feature 007 and 006 results; rule-based own-listing volatility regimes, expanding 33/67 percentiles | Implemented, awaiting owner review (not committed) |
| `009-rag-date-cutoff.md` | Date-cutoff retrieval: embedding port, pgvector chunks, user-scoped ingestion, search, cutoff audit | Implemented, live-verified; final review pending; NOT complete |

Not yet delivered: Feature 002 final review (docs sweep, live-PostgreSQL verification). Features 005-008: see their rows.
Feature 009 is implemented and live-verified (PostgreSQL 16, pgvector, Ollama) but NOT complete (pending owner sign-off).
Post-fix results, 2026-10-16 (recorded, not rerun when this note was written): portable full suite 2,057 passed,
83 skipped; full live suite 2,140 passed, 0 skipped; targeted post-fix suite 87 passed, 0 skipped. Earlier 009
counts in its spec and plan are historical.

Rules for these files: Markdown under 200 lines; no real tradebook data, symbols, ids or prices; update the matching spec
in the same change as the code.
