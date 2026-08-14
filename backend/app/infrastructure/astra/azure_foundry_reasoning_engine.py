from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from app.infrastructure.astra.reasoning_types import (
    ReasoningToolCall,
    ReasoningToolResult,
    ReasoningTurn,
)
from app.services.ai.astra_prompts import ASTRA_SYSTEM_INSTRUCTIONS
from app.services.ai.tool_definitions import TOOLS

if TYPE_CHECKING:
    from openai import OpenAI

_RESPONSE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,200}$")


class AzureFoundryReasoningEngine:
    """Encapsulates Azure AI Foundry Responses API invocation for Astra reasoning."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        *,
        system_instructions: str = ASTRA_SYSTEM_INSTRUCTIONS,
        max_output_tokens: int = 2000,
    ) -> None:
        self._client = client
        self._model = model
        self._system_instructions = system_instructions
        self._max_output_tokens = max_output_tokens

    def generate_response(
        self,
        user_input: str,
        tool_executor: Any | None = None,
    ) -> str:
        request: dict[str, Any] = {
            "model": self._model,
            "instructions": self._system_instructions,
            "max_output_tokens": self._max_output_tokens,
            "input": user_input,
        }
        if tool_executor is not None:
            request["tools"] = TOOLS

        response = self._client.responses.create(**request)
        return getattr(response, "output_text", "")

    def initial_reasoning(
        self,
        *,
        user_input: str,
        include_tools: bool,
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn:
        request: dict[str, Any] = {
            "model": self._model,
            "instructions": self._system_instructions,
            "max_output_tokens": self._max_output_tokens,
            "input": user_input,
        }
        if include_tools:
            request["tools"] = TOOLS

        response = self._client.responses.create(
            **request,
            timeout=self._remaining_budget(deadline_monotonic),
        )
        return self._to_reasoning_turn(response)

    def followup_reasoning(
        self,
        *,
        previous_response_id: str,
        tool_results: list[ReasoningToolResult],
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn:
        if not isinstance(previous_response_id, str) or not _RESPONSE_ID_RE.fullmatch(previous_response_id):
            raise ValueError("Invalid response id")

        response = self._client.responses.create(
            model=self._model,
            instructions=self._system_instructions,
            max_output_tokens=self._max_output_tokens,
            previous_response_id=previous_response_id,
            input=[
                self._build_tool_output_payload(tool_result)
                for tool_result in tool_results
            ],
            tools=TOOLS,
            timeout=self._remaining_budget(deadline_monotonic),
        )
        return self._to_reasoning_turn(response)

    def _to_reasoning_turn(self, response: Any) -> ReasoningTurn:
        raw_response_id = getattr(response, "id", None)
        if raw_response_id is None:
            response_id = None
        elif isinstance(raw_response_id, str) and _RESPONSE_ID_RE.fullmatch(raw_response_id):
            response_id = raw_response_id
        else:
            raise ValueError("Malformed response id")

        output_text = getattr(response, "output_text", "")
        if output_text is None:
            output_text = ""
        elif not isinstance(output_text, str):
            output_text = str(output_text)

        raw_output = getattr(response, "output", None)
        if raw_output is None:
            raw_output = []
        if not isinstance(raw_output, list):
            raise ValueError("Malformed provider response")

        tool_calls: list[ReasoningToolCall] = []
        for item in raw_output:
            if getattr(item, "type", None) != "function_call":
                continue

            tool_calls.append(
                ReasoningToolCall(
                    call_id=self._extract_call_id(item),
                    name=self._extract_tool_name(item),
                    arguments=self._parse_arguments(getattr(item, "arguments", {})),
                )
            )

        if tool_calls and response_id is None:
            raise ValueError("Azure response missing id")

        return ReasoningTurn(
            response_id=response_id,
            output_text=output_text,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _extract_tool_name(item: Any) -> str:
        name = getattr(item, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("Function call item missing name")
        return name

    @staticmethod
    def _extract_call_id(item: Any) -> str:
        call_id = getattr(item, "call_id", None)
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("Function call item missing call_id")
        return call_id

    @staticmethod
    def _parse_arguments(arguments: Any) -> dict[str, Any]:
        parsed = arguments
        if isinstance(arguments, str):
            parsed = json.loads(arguments)

        if not isinstance(parsed, dict):
            raise ValueError("Function call arguments must be an object")

        return parsed

    @staticmethod
    def _serialize_tool_result(tool_result: Any) -> str:
        if hasattr(tool_result, "model_dump_json"):
            return tool_result.model_dump_json()
        if hasattr(tool_result, "model_dump"):
            return json.dumps(tool_result.model_dump(), default=str)
        return json.dumps(tool_result, default=str)

    def _build_tool_output_payload(
        self,
        tool_result: ReasoningToolResult,
    ) -> dict[str, str]:
        return {
            "type": "function_call_output",
            "call_id": tool_result.call_id,
            "output": self._serialize_tool_result(tool_result.result),
        }

    @staticmethod
    def _remaining_budget(deadline_monotonic: float | None) -> float | None:
        if deadline_monotonic is None:
            return None
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("ASTRA execution timed out")
        return remaining
