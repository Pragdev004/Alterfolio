# Plan 011: Portfolio analysis wiring

Spec: `docs/specs/011-portfolio-analysis-wiring.md`. Steps commit separately; focused tests then full suite.

## Modules
1. `services/portfolio_analysis.py`: `AnalysisConfig`, `AnalysisFact`, `AnalysisFacts`, `derive_seed(user_id, as_of, name)`,
   `PortfolioAnalysisService(repo, series_service, config)`, `.analyse(user_id, as_of) -> AnalysisFacts`.
   Steps: load trades (cutoff) -> map `LedgerTrade` -> resolve+truncate series -> `analyze_biases` (006) ->
   `map_round_trips`/`fold_positions` -> `analyze_luck` (007) -> `analyze_regimes` (008) -> flatten facts.
2. `api/analyst_wiring.py`: `quant_tools_from(service) -> QuantTools` (intents bias_cost, luck_test, regime_split).
3. `api/routes/analyst.py`: `POST /api/analyst/ask`; `api/deps.py` provider hooks; `create_app` registers router,
   `app.state.history_provider`, `analysis_config`, `retriever` (default None).
4. `scripts/demo_analyst.py` + `tests/fixtures/analyst_demo_bars.json` and a builder `tests/fixtures/build_demo_fixture.py`.

## Tests (file `tests/test_portfolio_analysis*.py`) mapped to A#
- A1 trade_after_D_ignored; A2 post_D_bars_perturbed_facts_identical; A3 other_user_trades_not_read (service);
  A4 missing_series/undeclared_coverage/short_history give Unavailable + reason, no "0"; A5 identical_facts_and_seeds,
  seed_varies_by_user_date_name; A6 analyst_end_to_end_verified_true_numbers_match; A7 endpoint_isolation;
  A8 import_boundaries (extends existing AST test); A9 frozen_json_no_float; A10 demo_offline_report (script run);
  A11 no_network (socket guard in fixture).

## Steps
1 types + seed + trade loading/mapping (tests A1, A3, A5 seeds). 2 series + truncation (A2). 3 006/007/008 facts
(A4, A9). 4 analyst wiring (A6). 5 endpoint (A7). 6 demo (A10). Review, acceptance report, run report.

## Review additions (tests)
post-D void/late-recorded trade leaves facts unchanged (A1); trip closed on D is evaluated (A2); D=today/tomorrow -> 422;
180/181 bar boundary via service (A4); lowercase stored ISIN -> Unavailable not 500; per-None-field parametrised
"no 0" test; recursive no-float walk (A9); two users on one app (A7); seeds use separate params (A5).
