# Plan 015: Weak-model analyst harness

Status: UNREVIEWED BY OWNER. Builds on 010 (`docs/specs/010*`) and 011 (`docs/specs/011*`). No spec yet; this plan
is the contract until an as-built spec is written.

## Goal
A free hosted model (owner's choice: Groq `qwen/qwen3.8-27b`; also Groq Llama, OpenRouter `:free`, Gemini free tier,
any OpenAI-compatible endpoint) answers through `app/analyst/` with verified numbers at low token cost. The model is the
weakest part, so code decides everything it can: routing, tool calls, tool arguments, numbers, retries, fallback.

## Decisions
- D1 Provider-agnostic adapter `analyst/llm_langchain.py` (`LangChainLLM`) implements `AnalystLLM` via LangChain
  `init_chat_model`. Env: `AI_PROVIDER=langchain`, `AI_MODEL=<provider>:<model>` (e.g. `groq:qwen/qwen3.8-27b`,
  `openai:<model>`), optional `AI_BASE_URL` (OpenRouter/other OpenAI-compatible), `AI_API_KEY` (else the provider's
  own `<PROVIDER>_API_KEY`), `AI_TIMEOUT_SECONDS` (30), `AI_MAX_RETRIES` (2), `AI_TOKEN_BUDGET` (4000),
  `AI_REASONING_EFFORT` (unset = provider default; `none` recommended for qwen3), `AI_JSON_MODE` (1).
- D2 Settings come from the process env, then `backend/.env` (process env wins; `AI_DOTENV=0` disables the file).
  `.env` stays git-ignored; only `backend/.env.example` is committed. Tests snapshot and clear `AI_*` per test
  (conftest autouse fixture) so a developer `.env` never makes the offline suite call a model (rule 2).
- D3 Transport: provider SDK retries off (`max_retries=0`); the adapter retries itself on 429, 5xx, timeout and
  connection errors, at most `AI_MAX_RETRIES` extra tries, backoff 1s, 2s, ... capped at 8s (honours a numeric
  `Retry-After` up to the cap). Other errors and exhausted retries raise `AnalystLLMError`. Sleep is injectable.
- D4 Routing: `classify()` (rules) stays first and unchanged. The planner is called once only when the rules return
  `docs_only` AND the question has no document word (document/letter/report/note/news/filing/article/memo/said):
  that is "ambiguous". The model returns JSON `{intents, needs_docs, out_of_scope}`; `harness.parse_plan` accepts
  exactly those keys, intents a duplicate-free subset of `INTENTS`, strict bools, `out_of_scope` implies no intents and
  no docs, and not all-empty. Anything else (bad JSON, unknown value, extra key, error, budget) -> rules result. Never
  retried in a loop. Structured output is a JSON contract (JSON mode where the provider supports it) validated in code;
  no pydantic (analyst bans it) and no model function-calling.
- D5 Tools still run in code from the plan's intents; `user_id` and `as_of` always come from the server.
  `out_of_scope` -> fixed refusal text (no numbers), no tools, no retrieval, attempts 0, verified true.
  `needs_docs=false` (planner path only) skips retrieval. The rules path keeps 010 behaviour (always retrieves).
- D6 Placeholders: the drafting model writes prose with `{fact:NAME}` and `{doc:Dn}`, no digits. `harness.fill`
  substitutes the rendered value (`render` if given, else `value unit`) and adds the claim itself; `{doc:Dn}` becomes
  `document <chunk_id>`. Unknown name, an Unavailable fact, unknown doc id or a malformed/left-over brace is a repair
  error. `numbers.check` then runs unchanged on the filled text as the second guard. A style guard rejects BUY/SELL
  advice wording (`BUY`/`SELL` in capitals, "you should/we recommend ... buy|sell|hold").
- D7 Compact context: facts as one `name=value unit` line each (only the chosen intents' facts exist); passages are
  a prefix of the retrieved order, top-k 3, 1200 characters in total (`Dn` = position, so `fill` can map it back),
  passage dates omitted; fixed short system prompts (cacheable). Per-call input cap 1500 estimated tokens
  (chars / 4, ceiling) -> `AnalystLLMError` before sending.
- D8 Budget: per-question total (input + output) `AI_TOKEN_BUDGET`. Before each model call the graph skips the call if
  spent + the estimate (plan: 300; redraft: previous draft's usage) exceeds the budget. Output caps: plan 60 tokens,
  draft 400. Each call's `usage_metadata` (input/output tokens; estimated=true when the provider sends none) is
  returned with the result (never a shared mutable log; the app shares one LLM across requests).
- D9 Repair: at most 2 drafts (010 `MAX_ATTEMPTS`). Errors go back as at most 5 bullet lines of at most 160 chars,
  plus the same compact prompt; no conversation history. For a weak-model LLM (`fallback_to_template = True`) a
  failed second draft, a transport error or budget exhaustion falls back to `TemplateLLM(render)`; that text is
  checked too, verified stays true, and the answer says so in words (no digits). Other LLMs keep 010 behaviour
  (verified=false, facts verbatim): 010 test A3 is untouched.
- D10 `AnalystAnswer` gains `provenance` (default `{}` is never used; graph always fills it): `route`
  (rules | model | rules_fallback), `intents`, `out_of_scope`, `llm_calls` [{step, input_tokens, output_tokens,
  estimated}], `input_tokens`, `output_tokens`, `budget`, `fallback` (null | template), `fallback_reason`,
  `last_errors` (the harness's own repair messages, at most 5 x 160 chars; never model text). Ints only.
- D11 Reasoning models: `<think>...</think>` is stripped from every reply; Groq gets `reasoning_format=hidden` when
  the model id starts with `groq:` and `AI_REASONING_EFFORT` is set.

## Review round 1 (owner, 2026-11-13)
- D12 Semantic guard `analyst/semantics.py` (pure): the same `{fact:X}` twice in one sentence or the same number compared
  with itself; comparison words (higher/more/above/outperformed vs lower/less/below...) between two same-unit facts
  that the values contradict; positive/negative next to a fact of the other sign; an answer that asserts and denies a
  concept (statistical significance, skill vs luck), claims skill while saying not significant, or contains a sentence
  and its negation. A hit is a repair error, so `verified` now means numbers AND this guard (field name unchanged:
  API shape and 010 tests stay). Rule-shaped only; not a meaning check.
- D13 The 31 golden questions are the frozen tuning set (`TUNING_FINGERPRINT` sha256 pinned by a test). The owner's
  held-out set lives in `backend/evals/holdout.jsonl` (schema in `tests/analyst_eval/holdout.py`; ids/questions must not
  repeat the tuning set), scored by `eval_analyst.py --holdout` with unchanged prompts (report shows the prompt
  fingerprint).
- D14 `eval_analyst.py --runs N`: per metric mean/min/max over runs, per case k/N.
- D15 Chat clients cached per (provider, model, base URL, key digest, timeout, reasoning effort, JSON mode); the
  API's per-request `LangChainLLM` reuses them. `AnalystLLMError` carries only error type + HTTP status (provider text
  can name the account and reaches `provenance.last_errors`); the provider exception stays chained.

## Files
- New `app/analyst/harness.py` (pure, stdlib + analyst + domain): `is_ambiguous`, `parse_plan`, `fill`, `style_errors`,
  `error_bullets`, `select_passages`, `fact_lines`, `estimate_tokens`, `strip_reasoning`, prompts `PLAN_SYSTEM`,
  `DRAFT_SYSTEM`, `plan_prompt`, `draft_prompt`, `FALLBACK_NOTE`, `OUT_OF_SCOPE_TEXT`.
- New `app/analyst/settings.py`: `ai_env()` (process env over `backend/.env`, `python-dotenv` `dotenv_values`).
- New `app/analyst/llm_langchain.py`: `LangChainLLM(draft_model, plan_model, ...)`, `.from_env()`, `.plan()`, `.draft()`.
- Edit `types.py` (`Plan`, `Usage`, `Draft.usage`, `AnalystAnswer.provenance`), `graph.py` (planner, out_of_scope,
  needs_docs, fill, style guard, budget, template fallback, provenance), `service.py` (`langchain` provider; provider
  read via `ai_env`).
- New `backend/.env.example`; edit `pyproject.toml`, `constraints.txt`, `tests/conftest.py` (AI env isolation).
- New `tests/analyst_eval/`: `golden.py` (cases), `dumb.py` (scripted LangChain fake chat models), `scorer.py`,
  `runner.py`, `test_eval_offline.py`, `test_eval_live.py`; `tests/test_analyst_harness.py`,
  `tests/test_analyst_langchain.py`, `tests/test_analyst_semantics.py`, `tests/analyst_eval/holdout.py`. Script
  `scripts/eval_analyst.py [--live] [--runs N] [--holdout [PATH]] [--out DIR]` writes `docs/reports/eval-015-<date>.md`.

## Boundary changes
- langchain / langgraph / langchain_core imports: only `analyst/graph.py` and `analyst/llm_langchain.py` (was graph.py
  only). Provider packages (`langchain_groq`, `langchain_openai`) are never imported directly; `init_chat_model`
  loads them. `test_analyst_boundaries.py` LIBS gains `langchain_groq`, `langchain_openai`, `groq`, `openai`;
  `dotenv` only in `analyst/settings.py`. httpx rule unchanged. domain/quant/services boundaries unchanged.
- New pinned deps (runtime, pyproject exact + constraints): `langchain==1.4.6`, `langchain-groq==1.1.3`,
  `langchain-openai==1.7.2` (+ closure: groq, openai, tiktoken, jiter, regex). `python-dotenv` already pinned.

## Token budget (target per question, qwen3 at reasoning none)
plan call (ambiguous questions only) <= ~250 in / 60 out; draft ~350-800 in / <= 400 out; worst case two drafts plus
plan ~2600 < budget 4000. Measured (live, `docs/reports/eval-015-2026-11-13.md`, 31 cases x 5 runs, with D12): mean
352 tokens per answer (339-363), max 815; fallbacks 2.4 per run (2 rate-limit 429s across all runs; n02, n04 every
run on number words). The draft prompt names number words as forbidden (the 010 owner rule) after a first live run
fell back 4/31 times, 3 of them on number words.

## Tests
Harness (pure): parse_plan accepts the valid plan, rejects bad JSON, unknown intent, extra key, non-bool, duplicates,
oos+intents, all-empty, floats; fill substitutes rendered values and claims, rejects unknown/Unavailable/malformed;
doc mapping; style guard; error bullets capped; passage cap is a prefix and respects k and chars; estimate; strip think.
Graph: planner only for ambiguous docs_only, never for rule hits or document questions; bad plan -> rules_fallback;
out_of_scope refusal (no tools, no retrieval); needs_docs=false skips retrieval; template fallback after two bad
drafts / transport error / budget, verified true, note present; non-weak LLM keeps A3; provenance tokens summed.
Adapter: retry on 429/5xx/timeout with backoff then success; exhausted -> AnalystLLMError; 400 not retried; usage read
from usage_metadata or estimated; think stripped; from_env needs AI_MODEL, reads `.env`, process env wins, key never
in repr; input cap enforced. Boundaries: updated AST tests and pins.
Eval (offline): golden set >= 25 cases (routing, Unavailable, out-of-scope, injection, number-bait); DumbLLM (broken
JSON, wrong numbers, invented placeholders, empty draft, 429) -> every answer verified via honest fallback, number
faithfulness 100%, no bait number, tokens/answer reported; Oracle fake -> routing 100%, no fallback. Live: skipped
without `AI_MODEL` and a key; when run, faithfulness must be 100%.

## Steps
1 plan (this file). 2 types + harness + tests. 3 adapter + settings + deps + tests. 4 graph/service + tests.
5 eval harness offline. 6 live eval + report. Focused tests per step, full suite at the end. No commit (owner reviews).
