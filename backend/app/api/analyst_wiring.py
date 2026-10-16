"""Adapter: the 011 portfolio analysis service -> the 010 analyst's read-only quant tools (facts)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from uuid import UUID

from app.analyst.tools import QuantTools
from app.analyst.types import AnalystAnswer, Fact

_SOURCES = {"bias_cost": "006", "luck_test": "007", "regime_split": "008"}


def quant_tools_with_caveats(analyse):
    """(tools, caveats): `caveats()` lists notes owed to the reader, e.g. the static-universe survivorship flag whenever
    luck or regime facts (which contain luck results) were requested."""
    seen: dict = {}
    called: set[str] = set()

    def capturing(user_id, as_of):
        seen["r"] = analyse(user_id, as_of)
        return seen["r"]

    def tracked(intent, tool):
        def call(user_id, as_of):
            called.add(intent)
            return tool(user_id, as_of)
        return call

    tools = {i: tracked(i, t) for i, t in quant_tools_from(capturing).items()}

    def caveats() -> tuple[str, ...]:
        r = seen.get("r")
        if r is not None and called & {"luck_test", "regime_split"} and r.provenance.get("universe_static"):
            return (str(r.provenance.get("universe_note") or "static universe"),)
        return ()

    return tools, caveats


def apply_caveats(answer: AnalystAnswer, caveats: tuple[str, ...]) -> AnalystAnswer:
    """Append caveat notes to the text after verification (the notes carry no numbers)."""
    if not caveats:
        return answer
    return replace(answer, text=answer.text + "\n\nNote: " + "; ".join(caveats) + ".")


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
