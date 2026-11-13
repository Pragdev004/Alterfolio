"""Feature 015: run an analyst eval set and write a Markdown report.

    python scripts/eval_analyst.py [--live] [--runs N] [--holdout [PATH]] [--out DIR]     (from backend/)

Sets: the frozen 31-question tuning set (default) or the owner's held-out set (--holdout; default
backend/evals/holdout.jsonl), scored with the same prompts (the report records the prompt fingerprint).
Models: offline (default) the scripted DumbLLM, plus the Oracle on the tuning set; --live the model from AI_MODEL /
AI_API_KEY (process env, then backend/.env), exit 2 without them. --runs N repeats each run and reports mean/min/max.
Report: <out>/eval-015[-offline][-holdout]-<date>.md, out defaults to ../docs/reports.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.analyst.settings import ai_env  # noqa: E402
from tests.analyst_eval.dumb import dumb_llm, oracle_llm  # noqa: E402
from tests.analyst_eval.golden import CASES, PLANS  # noqa: E402
from tests.analyst_eval.holdout import HOLDOUT_PATH, HoldoutError, load_holdout  # noqa: E402
from tests.analyst_eval.runner import aggregate, report_runs, run  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--holdout", nargs="?", const=str(HOLDOUT_PATH), default=None)
    parser.add_argument("--out", default=str(BACKEND.parent / "docs" / "reports"))
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.holdout:
        try:
            cases, set_name = load_holdout(Path(args.holdout)), "held-out"
        except HoldoutError as exc:
            print(f"cannot load the held-out set: {exc}")
            return 2
    else:
        cases, set_name = CASES, "tuning"
    today = date.today()
    if args.live:
        env = ai_env()
        model = env.get("AI_MODEL", "")
        provider = model.partition(":")[0]
        if not provider or not (env.get("AI_API_KEY") or env.get(f"{provider.upper()}_API_KEY")):
            print("live eval needs AI_MODEL=<provider>:<model> and AI_API_KEY (or <PROVIDER>_API_KEY)")
            return 2
        from app.analyst.llm_langchain import LangChainLLM
        llm = LangChainLLM.from_env(env)
        models = [(f"Eval 015: live `{llm.label}`", llm.label, lambda: LangChainLLM.from_env(env))]
    else:
        models = [("Eval 015: offline DumbLLM", "dumb (scripted)", dumb_llm)]
        if not args.holdout:  # the oracle needs a plan per planner question; held-out lines may omit it
            models.append(("Eval 015: offline Oracle", "oracle (scripted)", lambda: oracle_llm(PLANS)))
    sections = []
    for title, label, make in models:
        runs = [run(make(), cases) for _ in range(args.runs)]
        sections.append(report_runs(runs, title=f"{title}, {set_name} set", model=label, run_date=today,
                                    set_name=set_name))
        agg = aggregate(runs)
        print(title, {k: v["mean"] for k, v in agg.items()})
    name = "eval-015" + ("" if args.live else "-offline") + ("-holdout" if args.holdout else "") + f"-{today}.md"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text("\n".join(sections), encoding="utf-8")
    print(f"wrote {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
