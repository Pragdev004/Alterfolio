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
| `004-quant-market-data-foundation.md` | Daily-bar port, Yahoo daily bars, `MarketBar`/`MarketSeries`, market-series service | Delivered in the working tree, pending commit (live Yahoo unverified) |

Not yet delivered: Feature 002 final review (docs sweep, live-PostgreSQL verification). Features 005+ are not started.

Rules for these files: Markdown under 200 lines; no real tradebook data, symbols, ids or prices; update the matching spec
in the same change as the code.
