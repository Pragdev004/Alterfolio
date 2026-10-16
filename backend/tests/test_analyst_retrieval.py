"""Feature 010 retrieval cutoff (A4)."""
from datetime import date, datetime, time, timezone

import pytest

from app.analyst.llm import FakeLLM, TemplateLLM
from app.analyst.service import ask
from app.analyst.types import Claim, Draft
from tests.analyst_support import CHUNK_LATE, CHUNK_OK, D, USER, FakeRetriever, FakeTools, chunk, dt, fact

Q = "What is my bias cost?"
CUTOFF = datetime.combine(D, time.max, tzinfo=timezone.utc)


def _tools():
    return FakeTools({"bias_cost": [fact()]})


def test_a4_retrieval_called_with_end_of_day_cutoff_never_later():
    r = FakeRetriever([chunk(CHUNK_OK, "Letter text.", dt(2026, 10, 9))])
    ask(USER, Q, D, llm=TemplateLLM(), tools=_tools(), retriever=r)
    assert len(r.calls) == 1
    assert r.calls[0]["cutoff"] == CUTOFF and r.calls[0]["user_id"] == USER


def test_a4_published_on_the_cutoff_day_is_eligible():
    r = FakeRetriever([chunk(CHUNK_OK, "Letter.", dt(2026, 10, 10, 23))])
    ans = ask(USER, Q, D, llm=TemplateLLM(), tools=_tools(), retriever=r)
    assert CHUNK_OK in [c.ref for c in ans.citations]


def test_a4_late_passage_never_reaches_citations_or_llm_even_if_retriever_returns_it():
    r = FakeRetriever([chunk(CHUNK_OK, "Early note.", dt(2026, 10, 9)),
                       chunk(CHUNK_LATE, "Future note 77.", dt(2026, 10, 11, 1))])
    llm = FakeLLM([Draft("Bias cost is 1234.50 INR.", (Claim("1234.50", "bias_cost.cost_inr"),))])
    ans = ask(USER, Q, D, llm=llm, tools=_tools(), retriever=r)
    refs = [c.ref for c in ans.citations]
    assert CHUNK_LATE not in refs
    assert all(p.chunk_id != CHUNK_LATE for p in llm.seen_passages[0])
    assert "Future note" not in ans.text


def test_a4_claim_citing_a_late_chunk_is_an_error():
    r = FakeRetriever([chunk(CHUNK_LATE, "Target price 77.", dt(2026, 10, 11))])
    bad = Draft("Target is 77.", (Claim("77", CHUNK_LATE),))
    ans = ask(USER, "annual letter?", D, llm=FakeLLM([bad, bad]), tools=FakeTools({}), retriever=r)
    assert ans.verified is False and "77" not in ans.text


def test_a4_provenance_cutoff_mismatch_is_rejected():
    r = FakeRetriever([chunk(CHUNK_OK, "x", dt(2026, 10, 9))], cutoff_echo=dt(2026, 10, 20))
    with pytest.raises(ValueError):
        ask(USER, Q, D, llm=TemplateLLM(), tools=_tools(), retriever=r)


def test_as_of_must_be_a_date_not_a_datetime_or_str():
    with pytest.raises(TypeError):
        ask(USER, Q, datetime(2026, 10, 10, tzinfo=timezone.utc), llm=TemplateLLM(), tools=_tools())
    with pytest.raises(TypeError):
        ask(USER, Q, "2026-10-10", llm=TemplateLLM(), tools=_tools())


def test_fact_dated_after_as_of_is_rejected():
    tools = FakeTools({"bias_cost": [fact(as_of=date(2026, 10, 11))]})
    with pytest.raises(ValueError):
        ask(USER, Q, D, llm=TemplateLLM(), tools=tools)


def test_passage_numbers_are_quotable_only_via_that_chunk():
    r = FakeRetriever([chunk(CHUNK_OK, "Fund AUM was 450 crore.", dt(2026, 10, 9))])
    good = Draft("The letter gives 450.", (Claim("450", CHUNK_OK),))
    ans = ask(USER, "annual letter?", D, llm=FakeLLM([good]), tools=FakeTools({}), retriever=r)
    assert ans.verified is True
    wrong = Draft("The letter gives 450.", (Claim("450", "bias_cost.cost_inr"),))
    ans2 = ask(USER, Q, D, llm=FakeLLM([wrong, wrong]), tools=_tools(), retriever=r)
    assert ans2.verified is False
