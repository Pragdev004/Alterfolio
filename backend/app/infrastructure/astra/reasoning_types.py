from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReasoningToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ReasoningToolResult:
    call_id: str
    result: Any


@dataclass(frozen=True)
class ReasoningTurn:
    response_id: str | None
    output_text: str
    tool_calls: list[ReasoningToolCall]
