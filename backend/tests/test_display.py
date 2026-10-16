"""Display formatting (percent, INR) is presentation-only; the number check accepts the rounded display of a fact."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from analysis_helpers import D_ASOF, NOW, FakeBars

from app.analyst.llm import TemplateLLM
from app.analyst.numbers import check
from app.analyst.types import UNAVAILABLE, Claim, Draft, Fact
from app.api.display import display_value, format_inr, format_percent, render_fact

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
DAY = date(2026, 9, 30)


@pytest.mark.parametrize("ratio,text", [
    ("0.003728", "0.37%"), ("0.00125", "0.12%"), ("0.00135", "0.14%"), ("0.00126", "0.13%"), ("-0.003728", "-0.37%"),
    ("-0.00125", "-0.12%"), ("0", "0.00%"), ("-0.000001", "0.00%"), ("1", "100.00%"), ("0.14214285714285715", "14.21%")])
def test_percent_rounds_half_even_at_two_decimals(ratio, text):
    assert format_percent(ratio) == text


@pytest.mark.parametrize("amount,text", [
    ("123456.78", "₹1,23,456.78"), ("1234567.5", "₹12,34,567.50"), ("0", "₹0.00"), ("999.999", "₹1,000.00"), ("100", "₹100.00"),
    ("1000", "₹1,000.00"), ("12345678.9", "₹1,23,45,678.90"), ("0.125", "₹0.12"), ("0.135", "₹0.14"), ("-123456.78", "-₹1,23,456.78"),
    ("-0.001", "₹0.00"), ("19.5947877483809985170819996720413198062922265276828123242572", "₹19.59")])
def test_inr_has_two_decimals_and_indian_grouping(amount, text):
    assert format_inr(amount) == text


def test_unavailable_is_never_formatted_as_a_number():
    for name, unit in (("luck.ALT.mean_excess", ""), ("bias.CHASING.cost_inr", "INR"), ("x.count", "")):
        assert display_value(name, UNAVAILABLE, unit) == "Unavailable"


def test_units_and_names_select_the_format_and_counts_stay_exact():
    assert display_value("bias.OVERTRADING.cost_inr", "105.8", "INR_LOWER_BOUND") == "₹105.80 (lower bound)"
    assert display_value("luck.last_trip.actual_return", "-0.0127", "RATIO_FEES_EXCLUDED") == "-1.27% (fees excluded)"
    assert display_value("luck.ALT.ci_upper", "0.0102", "") == "1.02%"
    assert display_value("luck.trip_count", "14", "") == "14"


def _fact(name, value, unit=""):
    return Fact(name, value, "007:x", DAY, unit)


def test_number_check_accepts_the_rounded_display_and_the_exact_value():
    f = _fact("luck.ALT.mean_excess", "0.003728123")
    assert check(Draft("luck.ALT.mean_excess is 0.37%", (Claim("0.37%", f.name),)), [f], [], DAY, render_fact) == []
    assert check(Draft("luck.ALT.mean_excess is 0.003728123", (Claim("0.003728123", f.name),)), [f], [], DAY, render_fact) == []


def test_number_check_rejects_a_wrong_rounded_value():
    f = _fact("luck.ALT.mean_excess", "0.003728123")
    errors = check(Draft("luck.ALT.mean_excess is 0.38%", (Claim("0.38%", f.name),)), [f], [], DAY, render_fact)
    assert errors and "does not equal" in errors[0]
    # without a renderer the rounded text is not accepted at all
    assert check(Draft("0.37%", (Claim("0.37%", f.name),)), [f], [], DAY)


def test_number_check_inr_and_negatives():
    pos, neg = _fact("bias.CHASING.cost_inr", "123456.78", "INR"), _fact("bias.DISPOSITION.cost_inr", "-123456.78", "INR")
    ok = Draft("bias.CHASING.cost_inr ₹1,23,456.78; bias.DISPOSITION.cost_inr -₹1,23,456.78",
               (Claim("₹1,23,456.78", pos.name), Claim("-₹1,23,456.78", neg.name)))
    assert check(ok, [pos, neg], [], DAY, render_fact) == []
    bad = Draft("bias.DISPOSITION.cost_inr ₹1,23,456.78", (Claim("₹1,23,456.78", neg.name),))  # sign dropped
    assert check(bad, [pos, neg], [], DAY, render_fact)


def test_template_llm_with_render_passes_the_check_and_unavailable_has_no_claim():
    facts = [_fact("luck.ALT.mean_excess", "-0.003564"), _fact("bias.CHASING.cost_inr", "19.5947", "INR"),
             _fact("luck.ALT.ci_lower", UNAVAILABLE), _fact("luck.trip_count", "14")]
    draft = TemplateLLM(render_fact).draft("q", facts, [], [])
    assert "luck.ALT.mean_excess: -0.36%" in draft.text and "luck.ALT.ci_lower: Unavailable" in draft.text
    assert "bias.CHASING.cost_inr: ₹19.59" in draft.text and len(draft.claims) == 3
    assert check(draft, facts, [], DAY, render_fact) == []


def test_coverage_summary_matches_the_analysis_facts(tmp_path):
    import demo_real
    sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
    from build_demo_fixture import tradebook_bytes
    s = demo_real.run([("a.csv", tradebook_bytes())], FakeBars(), D_ASOF, NOW, tmp_path / "r.md", luck_portfolios=20, replicates=200)
    by = {f["name"]: f["value"] for f in s["facts"]}
    cov, prov = s["coverage"], s["provenance"]
    assert cov["trips_analysed"] == by["luck.coverage.trips_analysed"] and cov["trips_total"] == by["luck.coverage.trips_total"]
    assert cov["excluded_listings"] == by["luck.coverage.excluded_listing_count"] == str(len(prov["excluded_listings"]))
    reviewed = set(prov["corporate_action_reviewed"] or [])
    assert cov["unreviewed_universe"] == sorted(f"{a}.{b}" for a, b, _ in prov["universe"] if f"{a}.{b}" not in reviewed)
    line = demo_real.summary_line(cov)
    assert f"trips analysed {by['luck.coverage.trips_analysed']} of {by['luck.coverage.trips_total']}" in line
    assert f"unreviewed universe listings {len(cov['unreviewed_universe'])}" in line
    assert f"Coverage: {line}" in (tmp_path / "r.md").read_text(encoding="utf-8")
