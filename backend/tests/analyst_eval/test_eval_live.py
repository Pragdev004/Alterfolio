"""Feature 015 eval, live: a real model through the harness. Skipped unless AI_MODEL and its key are set (rule 2).

Settings: the environment at the start of the run, then backend/.env. Runs one case per category to spare free-tier
quota; `scripts/eval_analyst.py --live` runs the whole golden set and writes docs/reports/eval-015-<date>.md.
"""
import pytest
from conftest import AI_ENV_AT_START

from app.analyst.settings import ai_env
from tests.analyst_eval.golden import CASES
from tests.analyst_eval.runner import report, run
from tests.analyst_eval.scorer import summary
from tests.analyst_support import D


def _live_env() -> dict:
    env = ai_env(AI_ENV_AT_START, use_dotenv=AI_ENV_AT_START.get("AI_DOTENV", "1") != "0")
    model = env.get("AI_MODEL", "")
    provider = model.partition(":")[0]
    if not provider or not (env.get("AI_API_KEY") or env.get(f"{provider.upper()}_API_KEY")):
        pytest.skip("live eval needs AI_MODEL=<provider>:<model> and AI_API_KEY (or <PROVIDER>_API_KEY)")
    return env


def test_live_model_answers_are_verified_and_faithful(tmp_path):
    env = _live_env()
    from app.analyst.llm_langchain import LangChainLLM
    llm = LangChainLLM.from_env(env)
    cases = list({c.category: c for c in CASES}.values())
    results = run(llm, cases)
    (tmp_path / "eval-015-live.md").write_text(report(results, title="Eval 015 (live subset)", model=llm.label,
                                                      run_date=D), encoding="utf-8")
    s = summary(results)
    assert s["faithful"] == s["cases"], [(r.case.id, r.problems) for r in results if not r.faithful]
    assert s["verified"] == s["cases"]  # a failing model ends in the verified template fallback, never unverified
