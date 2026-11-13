"""Feature 015 held-out set: `backend/evals/holdout.jsonl`, written by the owner, scored with the frozen harness.

One JSON object per line (blank lines ignored). Required: `id`, `category`, `question`, `intents` (subset of
bias_cost, luck_test, regime_split, backtest, or ["docs_only"], or [] when out of scope). Optional: `out_of_scope`
(bool), `docs` (keys of golden.DOCS: letter, inject, late), `bait` (numbers that must never appear), `plan` (only for
the offline oracle). Facts are golden.FACTS. Ids and questions must not repeat the tuning set.
"""
import json
from pathlib import Path

from app.analyst.classify import DOCS_ONLY, INTENTS
from tests.analyst_eval.golden import CASES, DOCS, Case

HOLDOUT_PATH = Path(__file__).resolve().parents[2] / "evals" / "holdout.jsonl"
_REQUIRED = {"id", "category", "question", "intents"}
_OPTIONAL = {"out_of_scope", "docs", "bait", "plan"}


class HoldoutError(ValueError):
    pass


def _strings(line_no: int, name: str, value) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise HoldoutError(f"line {line_no}: {name} must be a list of non-blank strings")
    return tuple(value)


def load_holdout(path: Path = HOLDOUT_PATH) -> tuple[Case, ...]:
    if not path.is_file():
        raise HoldoutError(f"held-out set not found: {path}")
    tuning_ids, tuning_questions = {c.id for c in CASES}, {c.question.strip().lower() for c in CASES}
    cases: list[Case] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise HoldoutError(f"line {line_no}: not JSON ({exc})") from exc
        if not isinstance(row, dict):
            raise HoldoutError(f"line {line_no}: must be a JSON object")
        if missing := _REQUIRED - set(row):
            raise HoldoutError(f"line {line_no}: missing key(s) {sorted(missing)}")
        if extra := set(row) - _REQUIRED - _OPTIONAL:
            raise HoldoutError(f"line {line_no}: unknown key(s) {sorted(extra)}")
        for name in ("id", "category", "question"):
            if not isinstance(row[name], str) or not row[name].strip():
                raise HoldoutError(f"line {line_no}: {name} must be non-blank text")
        intents = _strings(line_no, "intents", row["intents"]) if row["intents"] else ()
        if bad := [i for i in intents if i not in (*INTENTS, DOCS_ONLY)]:
            raise HoldoutError(f"line {line_no}: unknown intent(s) {bad}")
        docs = _strings(line_no, "docs", row.get("docs", [])) if row.get("docs") else ()
        if bad := [d for d in docs if d not in DOCS]:
            raise HoldoutError(f"line {line_no}: unknown doc(s) {bad}; use {sorted(DOCS)}")
        bait = _strings(line_no, "bait", row.get("bait", [])) if row.get("bait") else ()
        out_of_scope = row.get("out_of_scope", False)
        if not isinstance(out_of_scope, bool):
            raise HoldoutError(f"line {line_no}: out_of_scope must be true or false")
        if row["id"] in tuning_ids or row["question"].strip().lower() in tuning_questions:
            raise HoldoutError(f"line {line_no}: id or question repeats the tuning set")
        if row["id"] in {c.id for c in cases}:
            raise HoldoutError(f"line {line_no}: duplicate id {row['id']!r}")
        plan = row.get("plan")
        if plan is not None and not isinstance(plan, dict):
            raise HoldoutError(f"line {line_no}: plan must be an object")
        cases.append(Case(row["id"], row["category"], row["question"], intents, out_of_scope, docs, bait, plan))
    if not cases:
        raise HoldoutError(f"held-out set is empty: {path}")
    return tuple(cases)
