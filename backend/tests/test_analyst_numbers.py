"""Feature 010 number_check (A8)."""
import pytest

from app.analyst.numbers import canonical, check, numeric_tokens
from app.analyst.types import Claim, Draft, Passage
from tests.analyst_support import CHUNK_OK, D, dt, fact

F = [fact(name="m.cost", value="1234.50"), fact(name="m.ratio", value="0.2500", unit="ratio"),
     fact(name="m.na", value="Unavailable", unit="")]
P = [Passage(chunk_id=CHUNK_OK, source_id="note", text="Fund size 450 crore, up 15%.", published_at=dt(2026, 10, 9))]


def _c(text, *claims, passages=P):
    return check(Draft(text, tuple(Claim(v, s) for v, s in claims)), F, passages, D)


@pytest.mark.parametrize("a,b", [("1,234.50", "1234.5"), ("1234.500", "1234.5"), ("1.2345e3", "1234.5"),
                                 ("+7", "7"), ("-0.0", "0"), ("１２", "12")])
def test_canonical_normalises(a, b):
    assert canonical(a) == canonical(b)


def test_canonical_distinguishes_different_values():
    assert canonical("15") != canonical("5")
    assert canonical("12%") != canonical("0.12")


def test_clean_draft_has_no_errors():
    assert _c("Cost 1,234.50 and ratio 0.25.", ("1234.5", "m.cost"), ("0.25", "m.ratio")) == []


def test_token_without_claim_is_error():
    assert _c("Cost 1234.50 up 17.", ("1234.50", "m.cost"))


def test_claim_value_not_equal_to_cited_fact_is_error():
    assert _c("Ratio 1234.50.", ("1234.50", "m.ratio"))


def test_claim_with_unknown_source_is_error():
    assert _c("Cost 1234.50.", ("1234.50", "m.nothing"))


def test_claim_to_unavailable_fact_cannot_carry_a_number():
    assert _c("Value 0.", ("0", "m.na"))


def test_whole_token_match_only():
    assert _c("Rose 2025.", ("5", "m.cost"))
    assert _c("Rose 15.", ("5", "m.cost"))


def test_scale_words_and_number_words_are_errors():
    assert _c("About 12 lakh.", ("12", "m.cost"))
    assert _c("Cost was twelve thousand.", ("12", "m.cost"))
    assert _c("Roughly 5 bps.", ("5", "m.cost"))


def test_as_of_date_and_chunk_ids_and_fact_names_are_not_numbers():
    assert _c("As of 2026-10-10, see m.cost and chunk %s: 1234.50." % CHUNK_OK,
              ("1234.50", "m.cost")) == []


def test_cited_passage_date_is_not_an_unverified_number():
    text = "Note of 2026-10-09 says size 450."
    assert _c(text, ("450", CHUNK_OK)) == []
    assert _c("Note of 2026-10-09T12:00:00+00:00 says size 450.", ("450", CHUNK_OK)) == []


def test_uncited_passage_date_is_still_an_error():
    assert _c("Note of 2026-10-09 cost 1234.50.", ("1234.50", "m.cost"))


def test_other_dates_are_errors():
    assert _c("On 2026-10-11 cost 1234.50.", ("1234.50", "m.cost"))


def test_passage_number_requires_that_chunk_cited():
    assert _c("Size 450.", ("450", CHUNK_OK)) == []
    assert _c("Size 450.", ("450", "m.cost"))


def test_percent_not_equal_to_ratio():
    assert _c("Up 25%.", ("25%", "m.ratio"))


def test_numeric_tokens_whole_numbers_with_commas_and_exponent():
    assert numeric_tokens("a 1,234.50 b 3e2 c -4") == ["1,234.50", "3e2", "-4"]
