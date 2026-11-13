"""Feature 015 eval scorer: routing accuracy, verified rate, number faithfulness, semantic guard, tokens per answer.

Number faithfulness is checked independently of `app.analyst.numbers.check`: every number in the final text must be a
fact value, a fact's displayed value or a number in a document the answer cites, and no bait number may appear.
"""
import re
from dataclasses import dataclass

from app.analyst.numbers import canonical, numeric_tokens
from app.analyst.semantics import semantic_errors
from app.analyst.types import UNAVAILABLE, AnalystAnswer
from app.api.display import render_fact
from tests.analyst_eval.golden import DOCS, FACTS, Case


@dataclass(frozen=True)
class Result:
    case: Case
    answer: AnalystAnswer
    routing_ok: bool
    faithful: bool
    problems: tuple[str, ...]
    semantic: tuple[str, ...] = ()  # the semantic guard re-run on the final text (all facts)

    @property
    def semantic_ok(self) -> bool:
        return not self.semantic

    @property
    def tokens(self) -> int:
        return self.answer.provenance["input_tokens"] + self.answer.provenance["output_tokens"]


def _allowed() -> set[str]:
    out: set[str] = set()
    for facts in FACTS.values():
        for f in facts:
            if f.value != UNAVAILABLE:
                out.add(canonical(f.value))
                out |= {canonical(t) for t in numeric_tokens(render_fact(f))}
    return out


def score(case: Case, answer: AnalystAnswer, as_of) -> Result:
    prov = answer.provenance
    routing_ok = tuple(prov["intents"]) == case.intents and prov["out_of_scope"] == case.out_of_scope
    problems: list[str] = []
    text = answer.text
    cited = {c.ref for c in answer.citations if c.kind == "chunk"}
    allowed = _allowed()
    strip = [as_of.isoformat(), *(f.name for facts in FACTS.values() for f in facts)]
    for doc in DOCS.values():
        strip.append(doc.chunk_id)
        if doc.chunk_id in cited:
            allowed |= {canonical(t) for t in numeric_tokens(doc.text)}
    for name in sorted(strip, key=len, reverse=True):
        text = text.replace(name, " ")
    found = {canonical(t) for t in numeric_tokens(text)}
    for value in sorted(v for v in found if v not in allowed):
        problems.append(f"unbacked number {value}")
    for bait in case.bait:
        if canonical(bait) in found:
            problems.append(f"bait number {bait} appears")
    if re.search(r"\b(?:BUY|SELL)\b", answer.text):
        problems.append("advice wording in the answer")
    if case.out_of_scope and answer.citations:
        problems.append("out-of-scope answer cites sources")
    all_facts = [f for facts in FACTS.values() for f in facts]
    semantic = tuple(semantic_errors(answer.text, answer.text, all_facts))
    return Result(case, answer, routing_ok, not problems, tuple(problems), semantic)


def summary(results: list[Result]) -> dict:
    n = len(results)
    tokens = [r.tokens for r in results]
    drafted = [r for r in results if r.answer.provenance["llm_calls"]]
    return {
        "cases": n,
        "routing_ok": sum(r.routing_ok for r in results),
        "verified": sum(r.answer.verified for r in results),
        "faithful": sum(r.faithful for r in results),
        "semantic_ok": sum(r.semantic_ok for r in results),
        "fallbacks": sum(r.answer.provenance["fallback"] == "template" for r in results),
        "model_calls": sum(len(r.answer.provenance["llm_calls"]) for r in results),
        "input_tokens": sum(r.answer.provenance["input_tokens"] for r in results),
        "output_tokens": sum(r.answer.provenance["output_tokens"] for r in results),
        "mean_tokens_per_answer": sum(tokens) // n if n else 0,
        "mean_tokens_per_model_answer": sum(r.tokens for r in drafted) // len(drafted) if drafted else 0,
        "max_tokens_per_answer": max(tokens, default=0),
    }
