"""Injected collaborators of the graph: read-only quant tools and the cutoff-safe retriever (no adapter imports)."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.analyst.types import UNAVAILABLE, Fact

QuantTool = Callable[[UUID, date], Sequence[Fact]]
QuantTools = Mapping[str, QuantTool]


class Retriever(Protocol):
    """Matches `RetrievalService.search` (returns `SearchResult` or `Unavailable` from `app.domain.retrieval`)."""

    def search(self, *, user_id: UUID, query_text: str, cutoff: datetime, k: int): ...


def _unwired(intent: str) -> QuantTool:
    def tool(user_id: UUID, as_of: date) -> Sequence[Fact]:
        return (Fact(name=f"{intent}.status", value=UNAVAILABLE, source=intent, as_of=as_of),)
    return tool


def unwired_tools() -> QuantTools:
    """Default wiring: the quant analyses need assembled inputs no read-only service provides yet (plan 010 D2)."""
    return {intent: _unwired(intent) for intent in ("bias_cost", "luck_test", "regime_split", "backtest")}
