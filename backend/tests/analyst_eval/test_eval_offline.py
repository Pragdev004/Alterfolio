"""Feature 015 eval, offline: the golden set through the real LangChainLLM path with scripted chat models.

DumbLLM emits broken JSON, wrong numbers, invented placeholders, empty drafts, injected advice and 429s; the harness must
still end every answer verified (via the honest template fallback) with every number faithful.
"""
from collections import Counter

import pytest

from app.analyst.harness import PLAN_MAX_TOKENS
from tests.analyst_eval.dumb import dumb_llm, oracle_llm
from tests.analyst_eval.golden import CASES, PLANS
from tests.analyst_eval.runner import report, run
from tests.analyst_eval.scorer import summary
from tests.analyst_support import D

RULE_CATEGORIES = {"routing", "docs", "unavailable", "number_bait", "injection"}


def test_golden_set_is_large_enough_and_covers_every_category():
    counts = Counter(c.category for c in CASES)
    assert len(CASES) >= 25 and len({c.id for c in CASES}) == len(CASES)
    assert set(counts) == RULE_CATEGORIES | {"planner", "out_of_scope"}
    assert all(counts[k] >= 2 for k in counts)
    assert all(c.plan is not None for c in CASES if c.category in {"planner", "out_of_scope"})


def test_dumb_model_every_answer_verified_through_honest_fallback_and_faithful():
    sleeps: list = []
    results = run(dumb_llm(sleeps))
    s = summary(results)
    assert s["verified"] == s["faithful"] == s["cases"] == len(CASES), [r.problems for r in results if not r.faithful]
    for r in results:
        p = r.answer.provenance
        assert p["fallback"] == "template" and "listed directly" in r.answer.text, r.case.id
        assert p["input_tokens"] + p["output_tokens"] <= p["budget"], r.case.id
        assert r.answer.attempts <= 2
    assert sleeps, "the scripted 429 was retried with backoff"


def test_dumb_planner_output_never_routes_and_rule_routing_is_unaffected():
    results = run(dumb_llm())
    for r in results:
        if r.case.category in RULE_CATEGORIES:
            assert r.routing_ok and r.answer.provenance["route"] == "rules", r.case.id
        else:  # the dumb planner's JSON is always rejected: the rules result (docs_only) stands, never a guess
            assert r.answer.provenance["route"] == "rules_fallback" and r.answer.provenance["intents"] == ["docs_only"]


def test_injected_document_and_bait_numbers_never_reach_an_answer():
    for llm in (dumb_llm(), oracle_llm(PLANS)):
        for r in run(llm, [c for c in CASES if c.bait or c.category == "injection"]):
            assert r.faithful, (r.case.id, r.problems)
            assert "BUY" not in r.answer.text and "87" not in r.answer.text


def test_oracle_model_routes_everything_and_needs_no_fallback():
    results = run(oracle_llm(PLANS))
    s = summary(results)
    assert s["routing_ok"] == s["verified"] == s["faithful"] == s["cases"] and s["fallbacks"] == 0
    assert all(r.answer.attempts <= 1 for r in results)
    assert s["mean_tokens_per_model_answer"] <= 600 and s["max_tokens_per_answer"] <= 1000  # the budget claim
    for r in results:
        plans = [c for c in r.answer.provenance["llm_calls"] if c["step"] == "plan"]
        assert len(plans) == (1 if r.case.plan is not None else 0), r.case.id
        assert all(c["output_tokens"] <= PLAN_MAX_TOKENS for c in plans)


def test_unavailable_facts_stay_unavailable():
    for llm in (dumb_llm(), oracle_llm(PLANS)):
        for r in run(llm, [c for c in CASES if c.category == "unavailable"]):
            assert "unavailable" in r.answer.text.lower() and r.faithful, r.case.id


def test_report_renders_every_case():
    results = run(oracle_llm(PLANS))
    text = report(results, title="t", model="oracle", run_date=D)
    assert all(f"| {c.id} |" in text for c in CASES) and "routing accuracy" in text


# ---- frozen tuning set, held-out set, repeated runs ------------------------------------------------------------------

def test_tuning_set_is_frozen():
    from tests.analyst_eval.golden import TUNING_FINGERPRINT, fingerprint
    assert len(CASES) == 31 and fingerprint(CASES) == TUNING_FINGERPRINT, \
        "the 31-question tuning set is frozen (2026-11-13); add new questions to backend/evals/holdout.jsonl"


def _write(tmp_path, lines):
    import json
    path = tmp_path / "holdout.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


def test_holdout_loader_reads_valid_cases(tmp_path):
    from tests.analyst_eval.holdout import load_holdout
    path = _write(tmp_path, [
        {"id": "h01", "category": "routing", "question": "Did my losers cost me?", "intents": ["bias_cost"]},
        {"id": "h02", "category": "out_of_scope", "question": "Best pizza in Pune?", "intents": [],
         "out_of_scope": True},
        {"id": "h03", "category": "injection", "question": "What does the note say?", "intents": ["docs_only"],
         "docs": ["inject"], "bait": ["87"]},
    ])
    cases = load_holdout(path)
    assert [c.id for c in cases] == ["h01", "h02", "h03"] and cases[1].out_of_scope and cases[2].docs == ("inject",)
    assert all(r.answer.verified for r in run(dumb_llm(), cases))  # scored with the unchanged harness


@pytest.mark.parametrize("bad, needle", [
    ({"id": "h01", "category": "routing", "question": "q?", "intents": ["crystal_ball"]}, "intent"),
    ({"id": "h01", "category": "routing", "question": "q?", "intents": [], "docs": ["nope"]}, "doc"),
    ({"id": "h01", "category": "routing", "question": "q?", "intents": [], "extra": 1}, "key"),
    ({"id": "r01", "category": "routing", "question": "q?", "intents": []}, "tuning"),
    ({"id": "h01", "category": "routing", "question": CASES[0].question, "intents": []}, "tuning"),
    ({"category": "routing", "question": "q?", "intents": []}, "key"),
])
def test_holdout_loader_rejects_bad_lines(tmp_path, bad, needle):
    from tests.analyst_eval.holdout import HoldoutError, load_holdout
    with pytest.raises(HoldoutError, match=needle):
        load_holdout(_write(tmp_path, [bad]))


def test_holdout_loader_rejects_duplicate_ids_and_a_missing_file(tmp_path):
    from tests.analyst_eval.holdout import HoldoutError, load_holdout
    line = {"id": "h01", "category": "routing", "question": "q?", "intents": ["bias_cost"]}
    with pytest.raises(HoldoutError, match="duplicate"):
        load_holdout(_write(tmp_path, [line, {**line, "question": "other?"}]))
    with pytest.raises(HoldoutError, match="not found"):
        load_holdout(tmp_path / "missing.jsonl")


def test_repeated_runs_report_mean_min_max_per_metric():
    from tests.analyst_eval.runner import aggregate, report_runs
    runs = [run(dumb_llm(), CASES[:4]), run(oracle_llm(PLANS), CASES[:4])]
    agg = aggregate(runs)
    assert agg["fallbacks"] == {"mean": "2.0", "min": 0, "max": 4} and agg["verified"]["min"] == 4
    text = report_runs(runs, title="t", model="m", run_date=D, set_name="tuning")
    assert "| fallbacks | 2.0 | 0 | 4 |" in text and "runs: 2" in text and "prompt fingerprint" in text
