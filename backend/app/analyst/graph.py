"""The LangGraph state machine: classify -> quant_tools -> retrieve -> draft -> number_check -> (draft | finalize)."""

from datetime import date, datetime, time, timezone
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.analyst.classify import DOCS_ONLY, classify
from app.analyst.llm import AnalystLLM, AnalystLLMError, fact_line
from app.analyst.numbers import check
from app.analyst.tools import QuantTools, Retriever, unwired_tools
from app.analyst.types import AnalystAnswer, Citation, Draft, Fact, Passage
from app.domain.retrieval import Unavailable, to_utc, validate_text

MAX_ATTEMPTS = 2
SEARCH_K = 5


def cutoff_for(as_of: date) -> datetime:
    """The last instant of the UTC calendar day `as_of` (inclusive, matching 009 `is_eligible`)."""
    return datetime.combine(as_of, time.max, tzinfo=timezone.utc)


class State(TypedDict, total=False):
    user_id: UUID
    question: str
    as_of: date
    intents: tuple[str, ...]
    facts: tuple[Fact, ...]
    passages: tuple[Passage, ...]
    draft: Draft | None
    errors: tuple[str, ...]
    attempts: int
    answer: AnalystAnswer


def build_graph(llm: AnalystLLM, tools: QuantTools | None, retriever: Retriever | None):
    tools = unwired_tools() if tools is None else tools

    def classify_node(state: State) -> dict:
        return {"intents": classify(state["question"])}

    def quant_node(state: State) -> dict:
        facts: list[Fact] = []
        for intent in state["intents"]:
            if intent == DOCS_ONLY:
                continue
            tool = tools.get(intent) or unwired_tools()[intent]
            for fact in tool(state["user_id"], state["as_of"]):
                if not isinstance(fact, Fact):
                    raise TypeError("quant tools must return Fact values")
                if fact.as_of > state["as_of"]:
                    raise ValueError(f"fact {fact.name} is dated {fact.as_of}, after as_of {state['as_of']}")
                facts.append(fact)
        names = [f.name for f in facts]
        if len(set(names)) != len(names):
            raise ValueError("fact names must be unique")
        return {"facts": tuple(facts)}

    def retrieve_node(state: State) -> dict:
        if retriever is None:
            return {"passages": ()}
        cutoff = cutoff_for(state["as_of"])
        result = retriever.search(user_id=state["user_id"], query_text=validate_text("question", state["question"]),
                                  cutoff=cutoff, k=SEARCH_K)
        if isinstance(result, Unavailable):
            return {"passages": ()}
        if to_utc("cutoff", result.provenance.cutoff) != cutoff:
            raise ValueError("the retriever answered for a different cutoff than requested")
        kept = tuple(
            Passage(str(c.chunk_id), c.source_id, c.text, to_utc("published_at", c.published_at))
            for c in result.chunks if to_utc("published_at", c.published_at) <= cutoff
        )
        return {"passages": kept}

    def draft_node(state: State) -> dict:
        attempts = state.get("attempts", 0) + 1
        try:
            draft = llm.draft(state["question"], state["facts"], state["passages"], state.get("errors", ()))
        except AnalystLLMError as exc:
            return {"attempts": attempts, "draft": None, "errors": (f"the model failed: {exc}",)}
        if not isinstance(draft, Draft):
            return {"attempts": attempts, "draft": None, "errors": ("the model returned something that is not a Draft",)}
        return {"attempts": attempts, "draft": draft, "errors": ()}

    def check_node(state: State) -> dict:
        draft = state["draft"]
        if draft is None:
            return {}
        errors = check(draft, state["facts"], state["passages"], state["as_of"])
        if not draft.text.strip():
            errors.append("the draft text is empty")
        return {"errors": tuple(errors)}

    def route(state: State) -> str:
        return "draft" if state["errors"] and state["attempts"] < MAX_ATTEMPTS else "finalize"

    def finalize_node(state: State) -> dict:
        verified = not state["errors"]
        facts, passages, draft = state["facts"], state["passages"], state["draft"]
        if verified:
            text = draft.text
        elif facts:
            text = "\n".join(fact_line(f) for f in facts)
        else:
            text = "No verified facts are available for this question."
        citations = [Citation("tool", s) for s in dict.fromkeys(f.source for f in facts)]
        if verified:
            used = {c.source for c in draft.claims}
            citations += [Citation("chunk", p.chunk_id) for p in passages if p.chunk_id in used or p.chunk_id in text]
        return {"answer": AnalystAnswer(text, tuple(citations), verified, state["as_of"], state["attempts"])}

    g = StateGraph(State)
    for name, fn in (("classify", classify_node), ("quant_tools", quant_node), ("retrieve", retrieve_node),
                     ("draft", draft_node), ("number_check", check_node), ("finalize", finalize_node)):
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_edge("classify", "quant_tools")
    g.add_edge("quant_tools", "retrieve")
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", "number_check")
    g.add_conditional_edges("number_check", route, {"draft": "draft", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()
