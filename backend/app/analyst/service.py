"""Entry point: `ask(user_id, question, as_of)`. Provider selection follows AI_PROVIDER (default none, offline)."""

import os
from datetime import date, datetime
from uuid import UUID

from app.analyst.graph import build_graph
from app.analyst.llm import AnalystLLM, TemplateLLM
from app.analyst.tools import QuantTools, Retriever
from app.analyst.types import AnalystAnswer


def llm_from_provider(provider: str) -> AnalystLLM:
    if provider == "none":
        return TemplateLLM()
    if provider == "openai_compatible":
        from app.analyst.llm_openai import OpenAICompatibleLLM
        return OpenAICompatibleLLM.from_env()
    raise ValueError(f"unknown AI_PROVIDER {provider!r}; expected 'none' or 'openai_compatible'")


def ask(user_id: UUID, question: str, as_of: date, *, llm: AnalystLLM | None = None, tools: QuantTools | None = None,
        retriever: Retriever | None = None) -> AnalystAnswer:
    """Answer `question` using only facts and documents dated on or before `as_of` (a UTC calendar day)."""
    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be non-blank text")
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise TypeError("as_of must be a date, not a datetime or text")
    if llm is None:
        llm = llm_from_provider(os.environ.get("AI_PROVIDER", "none"))
    graph = build_graph(llm, tools, retriever)
    return graph.invoke({"user_id": user_id, "question": question, "as_of": as_of})["answer"]
