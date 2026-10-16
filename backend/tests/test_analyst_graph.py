"""Feature 010 graph behaviour (A1-A3, A5-A7, A10). FakeLLM/TemplateLLM only."""
import json
from dataclasses import FrozenInstanceError

import pytest

from app.analyst.llm import FakeLLM, TemplateLLM
from app.analyst.service import ask, llm_from_provider
from app.analyst.types import Claim, Draft
from tests.analyst_support import D, USER, FakeRetriever, FakeTools, fact

Q = "What is my bias cost?"


def _tools(*facts):
    return FakeTools({"bias_cost": list(facts) or [fact()]})


def _good():
    return Draft("Bias cost is 1234.50 INR.", (Claim("1234.50", "bias_cost.cost_inr"),))


def test_a1_happy_path_with_template_llm_is_verified():
    ans = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools())
    assert ans.verified is True and ans.attempts == 1 and ans.as_of == D
    assert "1234.50" in ans.text
    assert [c.ref for c in ans.citations] == ["bias_cost"]


def test_a1_happy_path_with_fake_llm_is_verified():
    ans = ask(USER, Q, D, llm=FakeLLM([_good()]), tools=_tools())
    assert ans.verified and ans.attempts == 1


def test_a2_invented_number_is_caught_and_redraft_fixes_it():
    bad = Draft("Bias cost is 9999 INR.", (Claim("9999", "bias_cost.cost_inr"),))
    llm = FakeLLM([bad, _good()])
    ans = ask(USER, Q, D, llm=llm, tools=_tools())
    assert ans.verified is True and ans.attempts == 2
    assert llm.seen_errors[0] == () and llm.seen_errors[1] != ()


def test_a2_number_in_text_without_claim_is_caught():
    bad = Draft("Bias cost is 1234.50 INR, up 17 percent.", (Claim("1234.50", "bias_cost.cost_inr"),))
    llm = FakeLLM([bad, _good()])
    ans = ask(USER, Q, D, llm=llm, tools=_tools())
    assert ans.attempts == 2 and llm.seen_errors[1] != ()


def test_a3_two_bad_drafts_give_unverified_facts_only():
    bad = Draft("Bias cost is 9999 INR, trust me.", (Claim("9999", "bias_cost.cost_inr"),))
    ans = ask(USER, Q, D, llm=FakeLLM([bad, bad]), tools=_tools())
    assert ans.verified is False and ans.attempts == 2
    assert "trust me" not in ans.text and "9999" not in ans.text
    assert "bias_cost.cost_inr" in ans.text and "1234.50" in ans.text


def test_a5_provider_none_is_offline_template():
    assert isinstance(llm_from_provider("none"), TemplateLLM)
    assert ask(USER, Q, D, tools=_tools()).verified is True  # default llm, no env, no network


def test_a5_unknown_provider_is_rejected_not_silently_defaulted():
    with pytest.raises(ValueError):
        llm_from_provider("mystery")


def test_a6_identical_inputs_give_identical_answers():
    a = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools())
    b = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools())
    assert a == b


def test_a7_unavailable_facts_pass_through_and_are_never_zero():
    u = fact(name="bias_cost.cost_inr", value="Unavailable")
    ans = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools(u))
    assert ans.verified is True
    assert "Unavailable" in ans.text
    assert "0" not in ans.text.replace("bias_cost.cost_inr", "")


def test_a7_unavailable_survives_the_fallback_too():
    u = fact(value="Unavailable")
    bad = Draft("Cost is 0.", (Claim("0", "bias_cost.cost_inr"),))
    ans = ask(USER, Q, D, llm=FakeLLM([bad, bad]), tools=_tools(u))
    assert ans.verified is False and "Unavailable" in ans.text


def test_a10_answer_is_frozen_json_and_has_no_float():
    ans = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools())
    with pytest.raises(FrozenInstanceError):
        ans.verified = False
    raw = json.dumps(ans.to_dict(), allow_nan=False)
    assert "NaN" not in raw and "Infinity" not in raw

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        else:
            assert not isinstance(x, float), "float in answer"
    walk(ans.to_dict())


def test_fact_rejects_floats():
    with pytest.raises((TypeError, ValueError)):
        fact(value=1.5)


def test_intents_only_call_matching_tools():
    tools = FakeTools({"bias_cost": [fact()], "luck_test": [fact(name="luck.p", value="0.1", source="luck_test")]})
    ask(USER, Q, D, llm=TemplateLLM(), tools=tools)
    assert [c[0] for c in tools.calls] == ["bias_cost"]
    assert tools.calls[0][1:] == (USER, D)


def test_docs_only_question_uses_no_quant_tools_and_retrieval_only():
    tools = FakeTools({"bias_cost": [fact()]})
    r = FakeRetriever([])
    ask(USER, "What did the annual letter say?", D, llm=TemplateLLM(), tools=tools, retriever=r)
    assert tools.calls == [] and len(r.calls) == 1
