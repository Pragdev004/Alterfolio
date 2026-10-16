"""OpenAICompatibleLLM against an in-process httpx MockTransport (no network)."""
import json

import httpx
import pytest

from app.analyst.llm import AnalystLLMError
from app.analyst.llm_openai import OpenAICompatibleLLM
from app.analyst.service import ask
from tests.analyst_support import D, USER, FakeTools, fact


def _llm(handler):
    return OpenAICompatibleLLM("http://localhost:11434/v1", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _reply(content):
    return lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_parses_a_json_draft_and_ask_verifies_it():
    content = json.dumps({"text": "Bias cost is 1234.50 INR.", "claims": [{"value": 1234.50, "source": "bias_cost.cost_inr"}]})
    ans = ask(USER, "my bias cost?", D, llm=_llm(_reply(content)), tools=FakeTools({"bias_cost": [fact()]}))
    assert ans.verified is True


def test_request_carries_facts_and_errors_and_no_float_parse():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return _reply(json.dumps({"text": "x", "claims": []}))(request)

    _llm(handler).draft("q", [fact()], [], ["fix it"])
    assert seen["temperature"] == 0 and "bias_cost.cost_inr: 1234.50 INR" in seen["messages"][1]["content"]
    assert "fix it" in seen["messages"][1]["content"]


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500),
    _reply("not json"),
    _reply(json.dumps({"claims": []})),
])
def test_failures_raise_analyst_llm_error(handler):
    with pytest.raises(AnalystLLMError):
        _llm(handler).draft("q", [fact()], [], [])


def test_a_model_failure_never_becomes_a_verified_answer():
    ans = ask(USER, "my bias cost?", D, llm=_llm(lambda r: httpx.Response(500)), tools=FakeTools({"bias_cost": [fact()]}))
    assert ans.verified is False and ans.attempts == 2 and "1234.50" in ans.text


def test_from_env_requires_url_and_model(monkeypatch):
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    with pytest.raises(ValueError):
        OpenAICompatibleLLM.from_env()
