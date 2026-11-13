"""Feature 015 semantic guard: self-comparisons, comparisons/signs contradicting the values, claim plus negation."""
import pytest

from app.analyst.llm import FakeLLM
from app.analyst.semantics import semantic_errors
from app.analyst.service import ask
from app.analyst.types import Draft
from tests.analyst_support import D, USER, FakeTools, fact

FACTS = [
    fact(name="bias.trips", value="14", unit=""), fact(name="luck.trips", value="9", unit=""),
    fact(name="luck.p_value", value="0.0812", unit=""), fact(name="regime.bear", value="-0.0213", unit="RATIO"),
    fact(name="regime.bull", value="0.0150", unit="RATIO"), fact(name="bias.cost", value="1234.50", unit="INR"),
]


def errs(raw, filled=None):
    return semantic_errors(raw, filled if filled is not None else raw, FACTS)


# ---- self-comparison -------------------------------------------------------------------------------------------------

def test_same_placeholder_twice_in_one_sentence_is_a_self_comparison():
    assert "itself" in errs("The p-value is {fact:luck.p_value}, which is not {fact:luck.p_value}.")[0]


def test_same_number_compared_with_itself_in_filled_text():
    assert "itself" in errs("The p-value is 0.0812, which is not 0.0812.")[0]


def test_same_placeholder_in_two_sentences_is_fine():
    assert errs("The p-value is {fact:luck.p_value}. Again, {fact:luck.p_value} is the p-value.") == []


# ---- comparisons and signs against the values --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "You made {fact:luck.trips} trips, more than the {fact:bias.trips} round trips.",
    "Bear excess {fact:regime.bear} was higher than bull excess {fact:regime.bull}.",
    "Bull excess {fact:regime.bull} was below bear excess {fact:regime.bear}.",
    "Bear excess {fact:regime.bear} outperformed bull excess {fact:regime.bull}.",
])
def test_comparison_words_that_contradict_the_values(text):
    assert any("contradicts" in e for e in errs(text))


@pytest.mark.parametrize("text", [
    "You made {fact:bias.trips} round trips, more than the {fact:luck.trips} luck trips.",
    "Bear excess {fact:regime.bear} was lower than bull excess {fact:regime.bull}.",
    "Bear excess {fact:regime.bear} was not higher than bull excess {fact:regime.bull}.",  # negated: consistent
    "Cost {fact:bias.cost} and trips {fact:bias.trips}.",                                  # no comparison word
])
def test_consistent_comparisons_pass(text):
    assert errs(text) == []


@pytest.mark.parametrize("text, bad", [
    ("Bear excess {fact:regime.bear} is positive.", True),
    ("Bull excess {fact:regime.bull}, which is negative, hurt you.", True),
    ("A positive bear excess of {fact:regime.bear}.", True),
    ("Bear excess {fact:regime.bear} is negative.", False),
    ("Bull excess {fact:regime.bull} was positive.", False),
])
def test_sign_words_must_match_the_value(text, bad):
    assert bool(errs(text)) is bad


# ---- claim plus its negation ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "The result is statistically significant. However, it is not statistically significant.",
    "Your results suggest skill rather than luck. The p-value shows this is not statistically significant.",
    "This shows skill. It is indistinguishable from random chance.",
    "Your edge is real. Your edge is not real.",
])
def test_a_claim_and_its_negation_in_one_answer(text):
    assert any("contradict" in e or "both" in e for e in errs(text))


@pytest.mark.parametrize("text", [
    "The p-value is {fact:luck.p_value}, so the result is not statistically significant.",
    "The results are consistent with chance rather than skill.",
    "Your results suggest a mix of skill and chance.",
    "Bias cost is {fact:bias.cost}. Trips were {fact:bias.trips}.",
])
def test_coherent_answers_pass(text):
    assert errs(text) == []


# ---- wired into the graph: a semantic error is a repair error -------------------------------------------------------------

def test_semantic_error_forces_a_redraft_and_blocks_verified():
    tools = FakeTools({"luck_test": [fact(name="luck.p_value", value="0.0812", source="luck_test", unit="")]})
    bad = Draft("The p-value is {fact:luck.p_value}, which is not {fact:luck.p_value}.")
    good = Draft("The p-value is {fact:luck.p_value}.")
    llm = FakeLLM([bad, good])
    ans = ask(USER, "Was it luck?", D, llm=llm, tools=tools)
    assert ans.verified and ans.attempts == 2 and any("itself" in e for e in llm.seen_errors[1])
    assert ask(USER, "Was it luck?", D, llm=FakeLLM([bad, bad]), tools=tools).verified is False
