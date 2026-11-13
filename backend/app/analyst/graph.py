"""The LangGraph state machine: classify -> quant_tools -> retrieve -> draft -> number_check -> (draft | finalize).

Feature 015: an LLM with `plan()` routes ambiguous questions once (validated in code); every draft has its `{fact:..}`
placeholders filled by code before the number check; an LLM with `fallback_to_template` gets a token
budget and a verified template fallback instead of an unverified answer (docs/plans/015)."""

from collections.abc import Callable
from datetime import date, datetime, time
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.analyst.classify import DOCS_ONLY, classify
from app.analyst.harness import (BULLET_CHARS, MAX_BULLETS, OUT_OF_SCOPE_TEXT, PLAN_ESTIMATE, fallback_note, fill,
                                 is_ambiguous, parse_plan, select_passages, style_errors)
from app.analyst.llm import AnalystLLM, AnalystLLMError, TemplateLLM, fact_line
from app.analyst.numbers import check
from app.analyst.tools import QuantTools, Retriever, unwired_tools
from app.analyst.types import AnalystAnswer, Citation, Draft, Fact, Passage, Usage
from app.domain.retrieval import Unavailable, to_utc, validate_text
from app.domain.timezones import IST

MAX_ATTEMPTS = 2
SEARCH_K = 5


def cutoff_for(as_of: date) -> datetime:
    """The last instant of the exchange-local (IST) calendar day `as_of` (inclusive, matching 009 `is_eligible`)."""
    return datetime.combine(as_of, time.max, tzinfo=IST)


class State(TypedDict, total=False):
    user_id: UUID
    question: str
    as_of: date
    intents: tuple[str, ...]
    route: str  # rules | model | rules_fallback
    needs_docs: bool
    out_of_scope: bool
    facts: tuple[Fact, ...]
    passages: tuple[Passage, ...]
    draft: Draft | None
    errors: tuple[str, ...]
    attempts: int
    usage: tuple[Usage, ...]
    last_cost: int
    stop: str | None  # weak-model early stop: "model_unavailable" or "budget"
    answer: AnalystAnswer


def _usage(items) -> tuple[Usage, ...]:
    items = tuple(items)
    if not all(isinstance(u, Usage) for u in items):
        raise TypeError("model usage must be Usage values")
    return items


def _cost(usage) -> int:
    return sum(u.input_tokens + u.output_tokens for u in usage)


def build_graph(llm: AnalystLLM, tools: QuantTools | None, retriever: Retriever | None,
                render: Callable[[Fact], str] | None = None):
    tools = unwired_tools() if tools is None else tools
    planner = getattr(llm, "plan", None)
    weak = getattr(llm, "fallback_to_template", False) is True
    budget = getattr(llm, "token_budget", None)
    budget = budget if isinstance(budget, int) and not isinstance(budget, bool) else None

    def over_budget(state: State, next_cost: int) -> bool:
        return budget is not None and _cost(state.get("usage", ())) + next_cost > budget

    def classify_node(state: State) -> dict:
        question = state["question"]
        out = {"intents": classify(question), "route": "rules", "needs_docs": True, "out_of_scope": False,
               "usage": (), "stop": None}
        if planner is None or not is_ambiguous(question, out["intents"]):
            return out
        if over_budget(state, PLAN_ESTIMATE):
            return {**out, "route": "rules_fallback"}
        try:
            text, usage = planner(question)
        except AnalystLLMError:
            return {**out, "route": "rules_fallback"}
        out["usage"] = _usage(usage)
        plan = parse_plan(text)
        if plan is None:  # bad JSON or unknown values: the rules result stands; never retried
            return {**out, "route": "rules_fallback"}
        intents = () if plan.out_of_scope else (plan.intents or (DOCS_ONLY,))
        return {**out, "route": "model", "intents": intents, "needs_docs": plan.needs_docs,
                "out_of_scope": plan.out_of_scope}

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
        if retriever is None or state["out_of_scope"] or not state["needs_docs"]:
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

    def after_retrieve(state: State) -> str:
        return "finalize" if state["out_of_scope"] else "draft"

    def draft_node(state: State) -> dict:
        if weak and over_budget(state, state.get("last_cost", 0)):
            return {"draft": None, "stop": "budget", "errors": state.get("errors") or ("token budget reached",)}
        attempts = state.get("attempts", 0) + 1
        try:
            draft = llm.draft(state["question"], state["facts"], state["passages"], state.get("errors", ()))
        except AnalystLLMError as exc:
            return {"attempts": attempts, "draft": None, "errors": (f"the model failed: {exc}",),
                    "stop": "model_unavailable" if weak else None}
        if not isinstance(draft, Draft):
            return {"attempts": attempts, "draft": None, "errors": ("the model returned something that is not a Draft",)}
        usage = _usage(draft.usage)
        return {"attempts": attempts, "draft": draft, "errors": (), "usage": state.get("usage", ()) + usage,
                "last_cost": _cost(usage)}

    def check_node(state: State) -> dict:
        draft = state["draft"]
        if draft is None:
            return {}
        shown = tuple(p for p, _ in select_passages(state["passages"]))
        draft, errors = fill(draft, state["facts"], shown, render)
        errors += check(draft, state["facts"], state["passages"], state["as_of"], render)
        errors += style_errors(draft.text)
        if not draft.text.strip():
            errors.append("the draft text is empty")
        return {"draft": draft, "errors": tuple(errors)}

    def after_check(state: State) -> str:
        if state.get("stop"):
            return "finalize"
        return "draft" if state["errors"] and state["attempts"] < MAX_ATTEMPTS else "finalize"

    def chunk_citations(draft: Draft, text: str, passages) -> list[Citation]:
        used = {c.source for c in draft.claims}
        return [Citation("chunk", p.chunk_id) for p in passages if p.chunk_id in used or p.chunk_id in text]

    def finalize_node(state: State) -> dict:
        usage = state.get("usage", ())
        provenance = {
            "route": state["route"], "intents": list(state["intents"]), "out_of_scope": state["out_of_scope"],
            "llm_calls": [u.to_dict() for u in usage], "input_tokens": sum(u.input_tokens for u in usage),
            "output_tokens": sum(u.output_tokens for u in usage), "budget": budget, "fallback": None,
            "fallback_reason": None,
            "last_errors": [e[:BULLET_CHARS] for e in state.get("errors", ())[:MAX_BULLETS]],  # harness text only
        }
        as_of, attempts = state["as_of"], state.get("attempts", 0)
        if state["out_of_scope"]:
            return {"answer": AnalystAnswer(OUT_OF_SCOPE_TEXT, (), True, as_of, attempts, provenance)}
        facts, passages, draft = state["facts"], state["passages"], state.get("draft")
        citations = [Citation("tool", s) for s in dict.fromkeys(f.source for f in facts)]
        if not state["errors"]:
            cited = tuple(citations + chunk_citations(draft, draft.text, passages))
            return {"answer": AnalystAnswer(draft.text, cited, True, as_of, attempts, provenance)}
        if weak:  # the deterministic template, itself checked; verified stays true and the text says why
            template = TemplateLLM(render).draft(state["question"], facts, passages, ())
            if not check(template, facts, passages, as_of, render):
                reason = state.get("stop") or "unverified"
                text = template.text + "\n\n" + fallback_note(reason)
                provenance.update(fallback="template", fallback_reason=reason)
                cited = tuple(citations + chunk_citations(template, text, passages))
                return {"answer": AnalystAnswer(text, cited, True, as_of, attempts, provenance)}
        if facts:
            text = "\n".join(fact_line(f, render) for f in facts)
        else:
            text = "No verified facts are available for this question."
        return {"answer": AnalystAnswer(text, tuple(citations), False, as_of, attempts, provenance)}

    g = StateGraph(State)
    for name, fn in (("classify", classify_node), ("quant_tools", quant_node), ("retrieve", retrieve_node),
                     ("draft", draft_node), ("number_check", check_node), ("finalize", finalize_node)):
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_edge("classify", "quant_tools")
    g.add_edge("quant_tools", "retrieve")
    g.add_conditional_edges("retrieve", after_retrieve, {"draft": "draft", "finalize": "finalize"})
    g.add_edge("draft", "number_check")
    g.add_conditional_edges("number_check", after_check, {"draft": "draft", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()
