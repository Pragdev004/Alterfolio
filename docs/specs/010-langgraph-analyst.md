# Spec 010: LangGraph analyst

Status: UNREVIEWED BY OWNER. Plan: `docs/plans/010-langgraph-analyst.md`.

## Goal
Answer a question about the user's portfolio as of date D using only deterministic quant results and documents dated
on or before D. Every number in the answer is traceable to a tool output. AI is never a source of a number.

## Design (fixed)
- Package `backend/app/analyst/` (service layer). `domain/` and `quant/` never import it or langgraph/langchain.
- Deps `langgraph`, `langchain-core`, pinned exactly (pyproject + `constraints.txt`). Only `analyst/graph.py` imports them.
- Port `AnalystLLM.draft(question, facts, passages, errors) -> Draft(text, claims[{value, source}])`.
  Impls: `FakeLLM` (scripted, tests), `TemplateLLM` (no model; default for `AI_PROVIDER=none`),
  `OpenAICompatibleLLM` (only for `AI_PROVIDER=openai_compatible`; httpx; never used in tests).
- Nodes: classify (keyword rules -> intents bias_cost, luck_test, regime_split, backtest, docs_only) -> quant_tools
  (existing read-only tools -> facts `{name, value, source}`; no new maths) -> retrieve (009, cutoff = end of day D UTC)
  -> draft -> number_check -> finalize. number_check errors and attempts < 2 -> draft again with errors; errors and
  attempts == 2 -> verified=false, facts verbatim, no free text; no errors -> verified=true.
- Output `AnalystAnswer(text, citations, verified, as_of, attempts)`: frozen, Decimals as strings, no floats/NaN.
- Entry `ask(user_id, question, as_of)`. `POST /api/analyst/ask` (user-isolated) only if the core is green.

## Acceptance criteria
- A1 Happy path with TemplateLLM/FakeLLM: verified=true, attempts=1, citations non-empty.
- A2 An invented number is caught; the redraft with errors fixes it; verified=true, attempts=2.
- A3 Two bad drafts: verified=false, text is the facts verbatim only, attempts=2.
- A4 Retrieval is called with cutoff == end of day D (never later); a passage dated after D never appears in
  citations or draft input, even if the retriever returns one.
- A5 `AI_PROVIDER=none` works offline (TemplateLLM, no network, no AI credentials).
- A6 Identical inputs give an identical answer (no clock, no randomness).
- A7 `Unavailable` facts pass through as "Unavailable" and are never turned into 0.
- A8 number_check: every numeric token must equal a claim value; every claim source must exist and the claim value
  must equal that fact (or appear in that cited passage), after canonical normalisation (commas, %, exponent, trailing zeros).
- A9 Import boundaries: domain/quant/models/repositories never import `app.analyst`, langgraph or langchain;
  analyst imports no adapter, httpx only in `analyst/llm_openai.py`.
- A10 Answer is frozen, JSON-serialisable, contains no float/NaN/inf.
- A11 (conditional) endpoint is user-isolated and 503 `ai_provider_not_configured` handling is unaffected; else deferred.

## Non-goals
Persistence, new quant maths, corporate actions, real LLM calls in tests.
