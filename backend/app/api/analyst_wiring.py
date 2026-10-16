"""Adapter: the 011 portfolio analysis service -> the 010 analyst's read-only quant tools (facts)."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from app.analyst.tools import QuantTools
from app.analyst.types import Fact

_SOURCES = {"bias_cost": "006", "luck_test": "007", "regime_split": "008"}


def quant_tools_from(analyse: Callable[[UUID, date], object]) -> QuantTools:
    """One tool per intent. `user_id` and `as_of` arrive per call (never bound here); one run is shared by the intents of
    a single question. `analyse` must return an object with `.facts` (name, value, source, unit)."""
    memo: dict[tuple[UUID, date], object] = {}

    def run(user_id: UUID, as_of: date):
        key = (user_id, as_of)
        if key not in memo:
            memo[key] = analyse(user_id, as_of)
        return memo[key]

    def tool_for(prefix: str):
        def tool(user_id: UUID, as_of: date) -> tuple[Fact, ...]:
            return tuple(Fact(name=f.name, value=f.value, source=f.source, as_of=as_of, unit=f.unit)
                         for f in run(user_id, as_of).facts if f.source.startswith(prefix + ":"))
        return tool

    return {intent: tool_for(prefix) for intent, prefix in _SOURCES.items()}
