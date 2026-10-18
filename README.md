# Alterfolio V2

**Tell a retail investor whether each decision was skill or luck, and prove no hindsight was used.**

Alterfolio V2 reads an NSE/BSE investor's own trades, measures them with deterministic code, and lets an analyst explain
the result in words. Every number comes from code, never from a model, and nothing dated after the question's as-of day
can reach an answer. Educational, not financial advice.

## Architecture

1. **Ledger.** Append-only trades (manual or Zerodha tradebook import); holdings are derived, never stored.
2. **Market data.** Provider port plus a Yahoo adapter; daily bars become point-in-time `MarketSeries` (`truncated_to` is the only narrowing).
3. **005 backtest.** Pure, deterministic backtesting foundation (strategy, sizing, execution models).
4. **006 / 007 / 008 analyses.** Bias cost and behaviour profile, luck test against random alternatives, volatility-regime split. Unknown stays `Unavailable`, never 0.
5. **009 date-cutoff RAG.** Document retrieval that cannot return anything published after the as-of day.
6. **010 LangGraph analyst.** Classify, call the analyses, retrieve, draft, then a number check rejects any figure that is not in the facts; an unverified answer returns the facts verbatim.

Layers: `api -> services -> repositories -> models`; `quant/` and `domain/` import only the standard library (enforced by an AST test).

## Run the offline demo (no network, no keys)

```
cd backend
python -m venv .venv && .venv\Scripts\Activate.ps1
python -m pip install -c constraints.txt -e ".[dev]"
python scripts/demo_analyst.py        # four questions on synthetic data -> docs/reports/demo-analyst-*.md
python scripts/report_html.py         # self-contained page -> docs/demo/alterfolio-demo.html
python -m pytest -q                   # full suite
```

The page `docs/demo/alterfolio-demo.html` shows each question, answer, verified yes/no, citations, the facts, and a
"What Alterfolio refuses to claim" section listing every Unavailable fact with its reason.

## Your own data (online, private)

`python scripts/demo_real.py TRADEBOOK.csv [MORE.csv]` imports your tradebooks (merged, imported once), fetches bars through
the Yahoo adapter (cached under `backend/.cache/`) and writes `docs/reports/demo-real-*`, which is git-ignored.
Fill `backend/config/corporate_actions_reviewed.toml` yourself; unreviewed listings are excluded from luck and regime, with the reason.

## Status

Test suite: **2346 passed, 0 skipped** (`python -m pytest -q -rs` from `backend/`; live-PostgreSQL tests need
`ALTERFOLIO_TEST_DATABASE_URL`). Tag: `v0.1-essence`. No frontend yet.

## Known limitations

- The luck universe is a static list (survivorship bias acknowledged); Nifty 50 membership is not configured, so the Nifty baseline is Unavailable.
- Corporate actions are not detected: the owner-reviewed register decides which listings are analysed. Five PSU banks are unverified and unreviewed.
- Separate tradebook uploads are order-dependent (a sell before its buy is rejected); the demo merges files first. Fix is deferred.
- Backfilled trades are recorded after the as-of day by nature, so they are disclosed (`late_recorded_row_count`), not filtered.
- A BSE listing is priced from the NSE series with the same ISIN (a disclosed price proxy).
- Luck and bias results are heuristics on small samples, not proof of skill; ISINs in config are from memory and unverified.
- No document retriever is wired into the API, and the analyst has no trading advice mode by design.

See `CLAUDE.md` (architecture, rules, known issues), `docs/design.md`, `docs/spec.md`, `docs/specs/`.

## Reset your local ledger (dev only)

To re-import tradebooks from scratch (for example after a fix): from `backend/`, with `ALTERFOLIO_DATABASE_URL` pointing at your local database,
run `python scripts/reset_ledger.py` for a dry run that prints what would go, then `python scripts/reset_ledger.py --yes`. It deletes only the
configured user's trades and import batches, refuses any non-local database, and is not part of the API. Then upload the oldest tradebook first.
