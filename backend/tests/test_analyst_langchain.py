"""Feature 015 LangChain adapter and AI settings, offline (scripted chat models; real models are only constructed)."""
import pytest

from app.analyst.harness import DRAFT_SYSTEM, MAX_INPUT_TOKENS, PLAN_SYSTEM
from app.analyst.llm import AnalystLLMError
from app.analyst.llm_langchain import LangChainLLM
from app.analyst.service import llm_from_provider
from app.analyst.settings import ai_env
from app.analyst.types import Passage
from tests.analyst_eval.dumb import FakeStatusError, ScriptedChatModel
from tests.analyst_support import dt, fact


def _llm(responses, **kw):
    script = list(responses)
    model = ScriptedChatModel(lambda s, u, i: script[i])
    sleeps: list = []
    llm = LangChainLLM(model, model, sleep=sleeps.append, **kw)
    return llm, model, sleeps


def test_draft_prompt_is_compact_fixed_and_carries_bullets():
    llm, model, _ = _llm(["a", "b"])
    passages = [Passage(str(i), "s", "word " * 400, dt(2026, 10, 1)) for i in range(5)]
    llm.draft("q?", [fact(), fact(name="x.y", value="Unavailable")], passages, ["number '9' is wrong"])
    llm.draft("other?", [fact()], [], [])
    first, second = model.calls
    assert first["system"] == second["system"] == DRAFT_SYSTEM  # fixed, cacheable
    assert "bias_cost.cost_inr=1234.50 INR\nx.y=Unavailable" in first["user"]
    assert first["user"].count("<D") <= 3 and len(first["user"]) < 2000
    assert "- number '9' is wrong" in first["user"] and "FIX" not in second["user"] and "DOCS" not in second["user"]


def test_plan_uses_the_plan_prompt_and_returns_raw_text_and_usage():
    llm, model, _ = _llm(['{"x": 1}'])
    text, usage = llm.plan("q?")
    assert text == '{"x": 1}' and model.calls[0]["system"] == PLAN_SYSTEM and model.calls[0]["user"] == "QUESTION: q?"
    assert usage[0].step == "plan" and usage[0].estimated is False and usage[0].input_tokens > 0


def test_retries_429_and_5xx_with_bounded_backoff_then_succeeds():
    llm, model, sleeps = _llm([FakeStatusError(429, retry_after="3"), FakeStatusError(503), "ok"])
    assert llm.draft("q", [fact()], [], []).text == "ok"
    assert len(model.calls) == 3 and sleeps == [3, 2]


def test_retry_after_is_capped():
    llm, _, sleeps = _llm([FakeStatusError(429, retry_after="120"), "ok"])
    llm.draft("q", [], [], [])
    assert sleeps == [8]


def test_timeouts_are_retried():
    llm, model, _ = _llm([TimeoutError("slow"), "ok"])
    assert llm.draft("q", [], [], []).text == "ok" and len(model.calls) == 2


def test_exhausted_retries_raise_analyst_llm_error():
    llm, model, sleeps = _llm([FakeStatusError(500)] * 3)
    with pytest.raises(AnalystLLMError, match="HTTP 500") as caught:
        llm.draft("q", [], [], [])
    assert len(model.calls) == 3 and sleeps == [1, 2]
    assert "org_" not in str(caught.value) and caught.value.__cause__ is not None  # provider text kept off the message


def test_provider_error_text_never_reaches_the_message():
    llm, _, _ = _llm([ValueError("Rate limit for organization org_secret123 reached")])
    with pytest.raises(AnalystLLMError) as caught:
        llm.draft("q", [], [], [])
    assert "org_secret123" not in str(caught.value) and "ValueError" in str(caught.value)


@pytest.mark.parametrize("error", [FakeStatusError(400), FakeStatusError(401), ValueError("bad request")])
def test_client_errors_are_not_retried(error):
    llm, model, sleeps = _llm([error, "never"])
    with pytest.raises(AnalystLLMError):
        llm.draft("q", [], [], [])
    assert len(model.calls) == 1 and sleeps == []


def test_usage_is_estimated_when_the_provider_sends_none_and_think_is_stripped():
    model = ScriptedChatModel(lambda s, u, i: "<think>long reasoning</think>Your cost is {fact:a}.", report_usage=False)
    draft = LangChainLLM(model).draft("q", [], [], [])
    assert draft.text == "Your cost is {fact:a}." and draft.usage[0].estimated is True and draft.usage[0].output_tokens > 0


def test_input_cap_is_enforced_before_any_call():
    llm, model, _ = _llm(["never"])
    with pytest.raises(AnalystLLMError, match="input cap"):
        llm.draft("q" * (MAX_INPUT_TOKENS * 4), [], [], [])
    assert model.calls == []


def test_from_env_requires_provider_and_model():
    for model in ("", "llama-3.1-8b-instant", "groq:"):
        with pytest.raises(ValueError):
            LangChainLLM.from_env({"AI_MODEL": model} if model else {})


def test_from_env_builds_a_groq_model_without_network_and_hides_the_key():
    llm = LangChainLLM.from_env({"AI_MODEL": "groq:qwen/qwen3.8-27b", "AI_API_KEY": "secret-test-key",
                                 "AI_REASONING_EFFORT": "default", "AI_TOKEN_BUDGET": "2500"})
    draft, plan = llm._draft_model, llm._plan_model
    assert draft.max_retries == 0 and draft.temperature < 1e-6 and draft.max_tokens == 400  # ChatGroq maps 0 to 1e-8
    assert draft.reasoning_format == "hidden"
    assert draft.request_timeout == 30 and plan.kwargs == {"response_format": {"type": "json_object"}}
    assert plan.bound.max_tokens == 60 and llm.token_budget == 2500
    assert "secret" not in repr(llm)


def test_from_env_openai_compatible_base_url_and_options():
    llm = LangChainLLM.from_env({"AI_MODEL": "openai:meta-llama/llama-3.3-70b-instruct:free", "OPENAI_API_KEY": "k",
                                 "AI_BASE_URL": "https://openrouter.ai/api/v1", "AI_JSON_MODE": "0",
                                 "AI_REASONING_EFFORT": "none", "AI_TIMEOUT_SECONDS": "12", "AI_MAX_RETRIES": "1"})
    assert llm._draft_model.openai_api_base == "https://openrouter.ai/api/v1"
    assert llm._draft_model.model_name == "meta-llama/llama-3.3-70b-instruct:free"
    assert llm._draft_model.request_timeout == 12 and llm._max_retries == 1
    assert not hasattr(llm._plan_model, "bound")  # JSON mode off: the plain model


def test_from_env_rejects_non_numeric_settings():
    with pytest.raises(ValueError, match="AI_TOKEN_BUDGET"):
        LangChainLLM.from_env({"AI_MODEL": "groq:m", "AI_API_KEY": "k", "AI_TOKEN_BUDGET": "lots"})


def test_ai_env_process_env_wins_over_dotenv_and_blank_is_unset(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AI_MODEL=groq:file-model\nAI_API_KEY=from-file\nAI_BASE_URL=\n# AI_PROVIDER=langchain\n"
                        "ALTERFOLIO_DATABASE_URL=x\n", encoding="utf-8")
    env = ai_env({"AI_MODEL": "groq:shell-model"}, path=env_file)
    assert env == {"AI_MODEL": "groq:shell-model", "AI_API_KEY": "from-file"}
    assert ai_env({"AI_DOTENV": "0"}, path=env_file) == {"AI_DOTENV": "0"}
    assert ai_env({}, path=env_file, use_dotenv=False) == {}


def test_the_suite_runs_with_ai_settings_cleared(monkeypatch):
    import os
    assert os.environ.get("AI_DOTENV") == "0" and "AI_PROVIDER" not in os.environ  # conftest autouse fixture


def test_llm_from_provider_langchain(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "groq:llama-3.1-8b-instant")
    monkeypatch.setenv("AI_API_KEY", "k")
    assert isinstance(llm_from_provider("langchain"), LangChainLLM)


# ---- client cache (one chat model pair per provider/model and client settings) -------------------------------------

def _env(**extra):
    return {"AI_MODEL": "groq:llama-3.1-8b-instant", "AI_API_KEY": "k1", **extra}


class _CheapModel:
    """Stands in for a provider client (real construction costs about a second each); records how often it is built."""

    built = 0

    def __init__(self, *a, **k):
        type(self).built += 1

    def bind(self, **k):
        return self


@pytest.fixture(autouse=True)
def _cheap_init(request, monkeypatch):
    if any(k in request.node.name for k in ("cache", "own_client", "reuses_the_client")):
        from app.analyst import llm_langchain
        monkeypatch.setattr(llm_langchain, "init_chat_model", _CheapModel)
        _CheapModel.built = 0


def test_from_env_reuses_the_client_for_the_same_provider_and_model():
    from app.analyst.llm_langchain import clear_model_cache
    clear_model_cache()
    a, b = LangChainLLM.from_env(_env()), LangChainLLM.from_env(_env())
    assert a._draft_model is b._draft_model and a._plan_model is b._plan_model and _CheapModel.built == 2


@pytest.mark.parametrize("change", [{"AI_MODEL": "groq:qwen/qwen3.8-27b"}, {"AI_API_KEY": "k2"},
                                    {"AI_TIMEOUT_SECONDS": "9"}, {"AI_JSON_MODE": "0"}, {"AI_REASONING_EFFORT": "none"},
                                    {"AI_BASE_URL": "https://example.invalid/v1"}])
def test_a_different_model_or_client_setting_gets_its_own_client(change):
    from app.analyst.llm_langchain import clear_model_cache
    clear_model_cache()
    assert LangChainLLM.from_env(_env())._draft_model is not LangChainLLM.from_env(_env(**change))._draft_model


def test_the_cache_key_never_holds_the_api_key():
    from app.analyst import llm_langchain
    llm_langchain.clear_model_cache()
    LangChainLLM.from_env(_env(AI_API_KEY="very-secret-value"))
    assert "very-secret-value" not in repr(list(llm_langchain._MODELS))
