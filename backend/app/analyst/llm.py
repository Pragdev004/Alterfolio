"""The AnalystLLM port and its two offline implementations (the HTTP one lives in llm_openai.py)."""

from collections.abc import Callable, Sequence
from typing import Protocol

from app.analyst.numbers import numeric_tokens
from app.analyst.types import UNAVAILABLE, Claim, Draft, Fact, Passage


class AnalystLLMError(Exception):
    """The model could not produce a draft (transport or format failure). Never swallowed into a fake answer."""


class AnalystLLM(Protocol):
    def draft(self, question: str, facts: Sequence[Fact], passages: Sequence[Passage],
              errors: Sequence[str]) -> Draft: ...


def fact_line(fact: Fact, render: Callable[[Fact], str] | None = None) -> str:
    if render is not None:
        return f"{fact.name}: {render(fact)}"
    unit = f" {fact.unit}" if fact.unit and fact.value != UNAVAILABLE else ""
    return f"{fact.name}: {fact.value}{unit}"


class FakeLLM:
    """Scripted drafts for tests; records what each call was given."""

    def __init__(self, drafts: Sequence[Draft]) -> None:
        self._drafts = list(drafts)
        self.seen_errors: list[tuple[str, ...]] = []
        self.seen_facts: list[tuple[Fact, ...]] = []
        self.seen_passages: list[tuple[Passage, ...]] = []

    def draft(self, question, facts, passages, errors) -> Draft:
        self.seen_errors.append(tuple(errors))
        self.seen_facts.append(tuple(facts))
        self.seen_passages.append(tuple(passages))
        index = len(self.seen_errors) - 1
        if index >= len(self._drafts):
            raise AnalystLLMError("FakeLLM script exhausted")
        return self._drafts[index]


class TemplateLLM:
    """No model: states each fact, one line per fact, and points at each retrieved document.
    With `render` (a display formatter) values are shown rounded and the claims carry the displayed number."""

    def __init__(self, render: Callable[[Fact], str] | None = None) -> None:
        self._render = render

    def draft(self, question, facts, passages, errors) -> Draft:
        lines = [fact_line(f, self._render) for f in facts]
        claims = [Claim(numeric_tokens(self._render(f))[0] if self._render else f.value, f.name) for f in facts if f.value != UNAVAILABLE]
        lines += [f"See document {p.chunk_id}." for p in passages]
        if not lines:
            lines = ["No quantitative facts or documents were available for this question."]
        return Draft("\n".join(lines), tuple(claims))
