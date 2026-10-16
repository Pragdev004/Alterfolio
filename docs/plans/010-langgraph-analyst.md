# Plan 010: LangGraph analyst

Spec: `docs/specs/010-langgraph-analyst.md`. Decisions made unattended (owner to confirm):
- D1 cutoff for date D = 23:59:59.999999 UTC of D (inclusive, matches 009 `is_eligible`).
- D2 quant tools are injected (`QuantTools`: intent -> callable(user_id, as_of) -> facts). The bias/luck/regime/backtest
  quant functions need large assembled inputs, no read-only service exists yet; the default wiring returns an
  `Unavailable` fact per intent. Real assembly deferred.
- D3 retriever injected (`Retriever` Protocol matching `RetrievalService.search`); analyst never imports an adapter.
- D4 Floats are rejected at the Fact boundary; tools must supply canonical strings. Fact has `as_of`, `unit`.
- D5 `Retriever` Protocol uses `domain.retrieval` types only (no sqlalchemy import in analyst).

## Modules (`backend/app/analyst/`)
- `types.py`: `Fact`, `Passage`, `Claim`, `Draft`, `AnalystAnswer`, `Citation` (frozen).
- `classify.py`: `classify(question) -> tuple[str, ...]`.
- `numbers.py`: `canonical(token)`, `numeric_tokens(text)`, `check(draft, facts, passages, as_of) -> list[str]`.
- `llm.py`: `AnalystLLM` Protocol, `FakeLLM`, `TemplateLLM`. `llm_openai.py`: `OpenAICompatibleLLM`.
- `tools.py`: `QuantTools`, `Retriever` Protocols, `unwired_tools()`.
- `graph.py`: langgraph `StateGraph` build; `run_graph(...)`.
- `service.py`: `ask(user_id, question, as_of, *, llm, tools, retriever) -> AnalystAnswer`; `llm_from_provider(name)`.

## Tests (`backend/tests/test_analyst_*.py`) -> A#
- test_analyst_graph: happy A1, redraft A2, two bad A3, determinism A6, unavailable A7, none-provider A5.
- test_analyst_retrieval: cutoff and late-passage A4.
- test_analyst_numbers: normalisation and loopholes A8.
- test_analyst_types: frozen / no float A10.
- test_import_boundaries (extend): A9.
- test_api_analyst (conditional): A11.
