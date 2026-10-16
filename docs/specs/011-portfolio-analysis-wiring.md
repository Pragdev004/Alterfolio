# Spec 011: Portfolio analysis wiring

Status: UNREVIEWED BY OWNER. Plan: `docs/plans/011-portfolio-analysis-wiring.md`.

## Goal
For a user and an as-of date D, run the existing 006 (bias cost, behaviour), 007 (luck test) and 008 (regime split)
analyses on that user's real effective trades and market data, and give the 010 analyst real facts. No change to
`domain/` or `quant/`.

## Design (fixed unless noted)
- `services/portfolio_analysis.py`: `PortfolioAnalysisService.analyse(user_id, as_of: date) -> AnalysisFacts`.
- D is an IST calendar day (as 010). `cutoff_utc` = end of D IST (`datetime.combine(D, time.max, IST)` as UTC); bars use
  the sealed boundary: `series.truncated_to(IST midnight of D+1)` keeps session dates <= D. If that instant is later than
  the series' own cutoff, no truncation is needed (all bars are already before today).
- Trades: `TradeRepository.list_effective(user_id, as_of=cutoff_utc)` (EXECUTED, not superseded, that user only), re-filtered
  in the service; mapped to `LedgerTrade` (id = `trades.id` text; charges known iff `charges_provided`, else
  `ChargeValue.unknown()`; ISIN passed as stored). Limitation: supersession recorded after D is applied (no as-known-at).
- Series: one per traded listing (its own exchange, no fallback) plus the luck universe, via
  `MarketSeriesService.resolve_series([listing], ...)`, history port injected. A listing that cannot be resolved has no
  series; 006/007/008 then answer Unavailable themselves.
- Benchmark: 008 uses each listing's own volatility; no benchmark is needed, none is invented.
- Config (`AnalysisConfig`, frozen, injected): universe `(Candidate)`, `nifty50 (Membership)`, `corporate_action_listings`,
  `corporate_action_reviewed` (default None = undeclared, so 007/008 luck is Unavailable by their own rule), parameters.
  Defaults carry no invented membership or corporate-action claims. The config is recorded in provenance.
- Seeds: `int.from_bytes(sha256(json[str(user_id), D.isoformat(), name])[:8], "big")`; names `luck_test`, `regime_split`;
  recorded in facts provenance. No clock inside the analyses; `LuckParameters.as_of` = `cutoff_utc`.
- `AnalysisFacts` (frozen): `facts` (name, value canonical Decimal text | "Unavailable", source `006|007|008:<field>`),
  `provenance` (as_of, cutoff, seeds, series fingerprints, universe, config, input fingerprints), `unavailable`
  (analysis -> reason). Statistic floats from 007 are converted once: `Decimal(repr(x))`, canonical text (never for money);
  NaN/inf -> "Unavailable". Never 0 for a missing value.
- Analyst port: `app/api/analyst_wiring.py` adapts the service to 010 `QuantTool`s (intents bias_cost, luck_test,
  regime_split) producing `Fact`. `services/` never imports `app.analyst`. Stub `unwired_tools` stays for tests.
- `POST /api/analyst/ask {question, as_of: date}` -> `AnalystAnswer.to_dict()`; user from `get_current_user_id`;
  AI_PROVIDER=none default; 503 `ai_provider_not_configured` handling unchanged.
- `backend/scripts/demo_analyst.py`: offline, fixture tradebook + recorded bar fixture, 4 questions, report
  `docs/reports/demo-analyst-YYYY-MM-DD.md`.

## Acceptance criteria
- A1 A trade after D never reaches any analysis.
- A2 No bar after D reaches any analysis: perturbing post-D bars leaves the facts identical.
- A3 User A's request never reads user B's trades (service, endpoint).
- A4 A missing input (series, declaration, history) gives "Unavailable" with a reason, never 0.
- A5 Same inputs give identical facts and seeds; seeds differ by user, date and analysis name.
- A6 Analyst end to end with real wiring: verified=true and every number matches a fact.
- A7 Endpoint isolation: two users get different facts; unknown user gets no data of another.
- A8 Import boundaries: services -> quant allowed, `services/portfolio_analysis.py` imports no analyst, adapter or httpx;
  `analyst/` imports no quant or services; domain/quant untouched (git diff).
- A9 AnalysisFacts frozen, JSON-serialisable, no float/NaN/inf.
- A10 Demo runs offline, writes the report; the post-D document question is refused or cited correctly.
- A11 No network in tests or demo.
