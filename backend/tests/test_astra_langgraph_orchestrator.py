from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.infrastructure.astra.azure_foundry_reasoning_engine import AzureFoundryReasoningEngine
from app.infrastructure.astra.langgraph_agent_orchestrator import LangGraphAgentOrchestrator
from app.infrastructure.astra.reasoning_types import (
    ReasoningToolCall,
    ReasoningToolResult,
    ReasoningTurn,
)
from app.services.ai.agent_orchestrator import (
    AgentOrchestrationRequest,
    AgentOrchestrationResult,
    IAgentOrchestrator,
)
from app.services.ai.tool_executor import GuardrailViolationError, ToolExecutor


class FakeResponsesAPI:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class StubReasoningEngine:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.initial_calls: list[dict] = []
        self.followup_calls: list[dict] = []

    def initial_reasoning(
        self,
        *,
        user_input: str,
        include_tools: bool,
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn:
        self.initial_calls.append(
            {
                "user_input": user_input,
                "include_tools": include_tools,
                "deadline_monotonic": deadline_monotonic,
            }
        )
        return self._to_turn(self._responses.pop(0))

    def followup_reasoning(
        self,
        *,
        previous_response_id: str,
        tool_results: list[ReasoningToolResult],
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn:
        self.followup_calls.append(
            {
                "previous_response_id": previous_response_id,
                "tool_results": tool_results,
                "deadline_monotonic": deadline_monotonic,
            }
        )
        return self._to_turn(self._responses.pop(0))

    @staticmethod
    def _to_turn(response: SimpleNamespace) -> ReasoningTurn:
        calls = [
            ReasoningToolCall(
                call_id=item.call_id,
                name=item.name,
                arguments=json.loads(item.arguments)
                if isinstance(item.arguments, str)
                else item.arguments,
            )
            for item in response.output
            if item.type == "function_call"
        ]
        return ReasoningTurn(
            response_id=response.id,
            output_text=response.output_text,
            tool_calls=calls,
        )


class SpyToolExecutor:
    def __init__(self, results: list[dict] | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict, float | None]] = []
        self._results = results or []
        self._error = error

    def execute(
        self,
        tool_name: str,
        arguments: dict,
        *,
        deadline_monotonic: float | None = None,
    ):
        self.calls.append((tool_name, arguments, deadline_monotonic))
        if self._error is not None:
            raise self._error
        if self._results:
            return self._results.pop(0)
        return {"ok": True}


def _response(
    *,
    response_id: str,
    output_text: str,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        output=tool_calls or [],
        output_text=output_text,
    )


def _tool_call(name: str, arguments, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


def test_application_orchestration_abstraction_exists() -> None:
    request = AgentOrchestrationRequest(user_input="hello")
    assert request.user_input == "hello"
    assert request.tool_executor is None


def test_no_tool_call_ends_after_reasoning() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(response_id="resp_1", output_text="final-no-tool"),
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine)

    result = orchestrator.run(AgentOrchestrationRequest(user_input="ping"))

    assert result.output_text == "final-no-tool"
    assert len(engine.initial_calls) == 1
    assert not engine.followup_calls


def test_one_tool_call_reasoning_then_tool_then_reasoning() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", '{"symbol":"TCS"}', "call_1")],
            ),
            _response(response_id="resp_2", output_text="final-with-tool"),
        ]
    )
    executor = SpyToolExecutor(results=[{"symbol": "TCS", "price": 100}])
    orchestrator = LangGraphAgentOrchestrator(engine)

    result = orchestrator.run(
        AgentOrchestrationRequest(user_input="analyze", tool_executor=executor)
    )

    assert result.output_text == "final-with-tool"
    assert executor.calls[0][0] == "get_stock_quote"
    assert executor.calls[0][1] == {"symbol": "TCS"}
    assert executor.calls[0][2] is None
    assert engine.followup_calls[0]["previous_response_id"] == "resp_1"
    assert len(engine.followup_calls[0]["tool_results"]) == 1


def test_multiple_tool_turns() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            ),
            _response(
                response_id="resp_2",
                output_text="",
                tool_calls=[_tool_call("get_company_news", {"symbol": "TCS"}, "call_2")],
            ),
            _response(response_id="resp_3", output_text="final-multi"),
        ]
    )
    executor = SpyToolExecutor(results=[{"symbol": "TCS"}, {"symbol": "TCS", "articles": []}])
    orchestrator = LangGraphAgentOrchestrator(engine)

    result = orchestrator.run(
        AgentOrchestrationRequest(user_input="multi", tool_executor=executor)
    )

    assert result.output_text == "final-multi"
    assert [c[0] for c in executor.calls] == ["get_stock_quote", "get_company_news"]
    assert all(call[2] is None for call in executor.calls)
    assert len(engine.followup_calls) == 2


def test_tool_executor_only_execution_boundary() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "INFY"}, "call_1")],
            ),
            _response(response_id="resp_2", output_text="done"),
        ]
    )

    class BoundaryExecutor:
        def __init__(self) -> None:
            self.execute_calls = 0

        def execute(
            self,
            tool_name: str,
            arguments: dict,
            *,
            deadline_monotonic: float | None = None,
        ):
            self.execute_calls += 1
            return {"tool": tool_name, "args": arguments}

    executor = BoundaryExecutor()
    orchestrator = LangGraphAgentOrchestrator(engine)

    result = orchestrator.run(AgentOrchestrationRequest(user_input="q", tool_executor=executor))

    assert result.output_text == "done"
    assert executor.execute_calls == 1


def test_unknown_tool_propagates_error() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("unknown_tool", {}, "call_1")],
            )
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine)

    with pytest.raises(ValueError, match="Unknown tool"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="bad",
                tool_executor=SpyToolExecutor(error=ValueError("Unknown tool: unknown_tool")),
            )
        )


def test_tool_exception_propagates_error() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            )
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine)

    with pytest.raises(RuntimeError, match="tool boom"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="boom",
                tool_executor=SpyToolExecutor(error=RuntimeError("tool boom")),
            )
        )


def test_requires_portfolio_grounding_in_orchestrator() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            )
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine, require_portfolio_grounding=True)

    with pytest.raises(GuardrailViolationError, match="Portfolio grounding is required"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="ground-me",
                tool_executor=SpyToolExecutor(results=[{"symbol": "TCS"}]),
            )
        )


def test_maximum_iteration_guard() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            ),
            _response(
                response_id="resp_2",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_2")],
            ),
            _response(
                response_id="resp_3",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_3")],
            ),
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine, max_iterations=2)

    with pytest.raises(RuntimeError, match="maximum reasoning iterations"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="loop",
                tool_executor=SpyToolExecutor(results=[{"ok": True}, {"ok": True}, {"ok": True}]),
            )
        )


def test_maximum_tool_call_guard() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[
                    _tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1"),
                    _tool_call("get_company_news", {"symbol": "TCS"}, "call_2"),
                ],
            )
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine, max_tool_calls=1)

    with pytest.raises(RuntimeError, match="maximum tool calls"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="too-many",
                tool_executor=SpyToolExecutor(results=[{"ok": True}, {"ok": True}]),
            )
        )


def test_cumulative_tool_call_guard_across_turns() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            ),
            _response(
                response_id="resp_2",
                output_text="",
                tool_calls=[_tool_call("get_company_news", {"symbol": "TCS"}, "call_2")],
            ),
        ]
    )

    with pytest.raises(RuntimeError, match="maximum tool calls"):
        LangGraphAgentOrchestrator(engine, max_tool_calls=1).run(
            AgentOrchestrationRequest(
                user_input="too-many",
                tool_executor=SpyToolExecutor(results=[{"ok": True}, {"ok": True}]),
            )
        )


def test_model_failure_propagates() -> None:
    class FailingReasoningEngine(StubReasoningEngine):
        def initial_reasoning(
            self,
            *,
            user_input: str,
            include_tools: bool,
            deadline_monotonic: float | None = None,
        ):
            raise RuntimeError("model failure")

    orchestrator = LangGraphAgentOrchestrator(FailingReasoningEngine(responses=[]))

    with pytest.raises(RuntimeError, match="model failure"):
        orchestrator.run(AgentOrchestrationRequest(user_input="x"))


def test_existing_orchestration_contract_compatibility() -> None:
    engine = StubReasoningEngine(
        responses=[_response(response_id="resp_1", output_text="contract-ok")]
    )

    adapter: IAgentOrchestrator = LangGraphAgentOrchestrator(engine)
    result = adapter.run(
        AgentOrchestrationRequest(user_input="ping", agent_run_id="run-fixed")
    )

    assert isinstance(result, AgentOrchestrationResult)
    assert result == AgentOrchestrationResult(
        output_text="contract-ok",
        agent_run_id="run-fixed",
    )


def test_azure_foundry_engine_preserves_responses_api_calls() -> None:
    first = _response(
        response_id="resp_1",
        output_text="",
        tool_calls=[_tool_call("get_stock_quote", '{"symbol":"TCS"}', "call_1")],
    )
    second = _response(response_id="resp_2", output_text="final")

    fake_responses = FakeResponsesAPI([first, second])
    fake_client = SimpleNamespace(responses=fake_responses)
    engine = AzureFoundryReasoningEngine(client=fake_client, model="test-deployment")

    initial_turn = engine.initial_reasoning(user_input="Analyze", include_tools=True)
    assert initial_turn.response_id == "resp_1"
    assert len(initial_turn.tool_calls) == 1

    followup_turn = engine.followup_reasoning(
        previous_response_id=initial_turn.response_id,
        tool_results=[
            ReasoningToolResult(
                call_id=initial_turn.tool_calls[0].call_id,
                result={"symbol": "TCS", "price": 100},
            )
        ],
    )

    assert followup_turn.output_text == "final"
    assert len(fake_responses.calls) == 2
    assert fake_responses.calls[0]["tools"]
    assert fake_responses.calls[1]["previous_response_id"] == "resp_1"


def test_azure_engine_malformed_json_arguments() -> None:
    first = _response(
        response_id="resp_1",
        output_text="",
        tool_calls=[_tool_call("get_stock_quote", "{bad-json", "call_1")],
    )
    engine = AzureFoundryReasoningEngine(
        client=SimpleNamespace(responses=FakeResponsesAPI([first])),
        model="test-deployment",
    )

    with pytest.raises(json.JSONDecodeError):
        engine.initial_reasoning(user_input="Analyze", include_tools=True)


def test_azure_engine_invalid_argument_shapes() -> None:
    for bad_args in (None, [], 10):
        first = _response(
            response_id="resp_1",
            output_text="",
            tool_calls=[_tool_call("get_stock_quote", bad_args, "call_1")],
        )
        engine = AzureFoundryReasoningEngine(
            client=SimpleNamespace(responses=FakeResponsesAPI([first])),
            model="test-deployment",
        )

        with pytest.raises(ValueError, match="arguments must be an object"):
            engine.initial_reasoning(user_input="Analyze", include_tools=True)


def test_azure_engine_missing_tool_name_or_call_id() -> None:
    missing_name = _response(
        response_id="resp_1",
        output_text="",
        tool_calls=[SimpleNamespace(type="function_call", arguments={}, call_id="call_1")],
    )
    missing_call_id = _response(
        response_id="resp_1",
        output_text="",
        tool_calls=[SimpleNamespace(type="function_call", name="get_stock_quote", arguments={})],
    )

    for payload, message in (
        (missing_name, "missing name"),
        (missing_call_id, "missing call_id"),
    ):
        engine = AzureFoundryReasoningEngine(
            client=SimpleNamespace(responses=FakeResponsesAPI([payload])),
            model="test-deployment",
        )
        with pytest.raises(ValueError, match=message):
            engine.initial_reasoning(user_input="Analyze", include_tools=True)


def test_azure_engine_missing_response_id_with_tool_calls() -> None:
    response = SimpleNamespace(
        id=None,
        output=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
        output_text="",
    )
    engine = AzureFoundryReasoningEngine(
        client=SimpleNamespace(responses=FakeResponsesAPI([response])),
        model="test-deployment",
    )

    with pytest.raises(ValueError, match="missing id"):
        engine.initial_reasoning(user_input="Analyze", include_tools=True)


def test_azure_engine_empty_model_output_text_normalized() -> None:
    response = SimpleNamespace(id="resp_1", output=[], output_text=None)
    engine = AzureFoundryReasoningEngine(
        client=SimpleNamespace(responses=FakeResponsesAPI([response])),
        model="test-deployment",
    )

    turn = engine.initial_reasoning(user_input="Analyze", include_tools=False)
    assert turn.output_text == ""


def test_followup_model_failure_propagates() -> None:
    class FailingFollowupEngine(StubReasoningEngine):
        def followup_reasoning(
            self,
            *,
            previous_response_id: str,
            tool_results: list[ReasoningToolResult],
            deadline_monotonic: float | None = None,
        ) -> ReasoningTurn:
            raise RuntimeError("model failure")

    engine = FailingFollowupEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            )
        ]
    )
    orchestrator = LangGraphAgentOrchestrator(engine)

    with pytest.raises(RuntimeError, match="model failure"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="x",
                tool_executor=SpyToolExecutor(results=[{"ok": True}]),
            )
        )


def test_multiple_tool_calls_in_single_turn() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[
                    _tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1"),
                    _tool_call("get_company_news", {"symbol": "TCS"}, "call_2"),
                ],
            ),
            _response(response_id="resp_2", output_text="done"),
        ]
    )
    executor = SpyToolExecutor(results=[{"ok": 1}, {"ok": 2}])

    result = LangGraphAgentOrchestrator(engine).run(
        AgentOrchestrationRequest(user_input="q", tool_executor=executor)
    )

    assert result.output_text == "done"
    assert len(executor.calls) == 2


def test_tool_executor_real_unknown_tool_error() -> None:
    executor = ToolExecutor(
        SimpleNamespace(
            portfolio=SimpleNamespace(get_portfolio_summary=lambda: {}),
            market=SimpleNamespace(get_stock_quote=lambda symbol: {"symbol": symbol}),
            news=SimpleNamespace(get_company_news=lambda symbol: {"symbol": symbol}),
        )
    )

    with pytest.raises(ValueError, match="Unknown tool"):
        executor.execute("not_real_tool", {})


def test_internal_type_error_is_not_retried_without_deadline() -> None:
    class TypeErrorReasoningEngine:
        def __init__(self) -> None:
            self.calls: list[float | None] = []

        def initial_reasoning(
            self,
            *,
            user_input: str,
            include_tools: bool,
            deadline_monotonic: float | None = None,
        ) -> ReasoningTurn:
            self.calls.append(deadline_monotonic)
            raise TypeError("internal type error")

        def followup_reasoning(
            self,
            *,
            previous_response_id: str,
            tool_results: list[ReasoningToolResult],
            deadline_monotonic: float | None = None,
        ) -> ReasoningTurn:
            raise AssertionError("followup should not be called")

    engine = TypeErrorReasoningEngine()
    orchestrator = LangGraphAgentOrchestrator(engine)

    with pytest.raises(TypeError, match="internal type error"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="hello",
                deadline_monotonic=time.monotonic() + 30.0,
            )
        )

    assert len(engine.calls) == 1
    assert engine.calls[0] is not None


def test_tool_executor_type_error_is_not_retried_without_deadline() -> None:
    engine = StubReasoningEngine(
        responses=[
            _response(
                response_id="resp_1",
                output_text="",
                tool_calls=[_tool_call("get_stock_quote", {"symbol": "TCS"}, "call_1")],
            )
        ]
    )

    class TypeErrorToolExecutor:
        def __init__(self) -> None:
            self.calls: list[float | None] = []

        def execute(
            self,
            tool_name: str,
            arguments: dict,
            *,
            deadline_monotonic: float | None = None,
        ):
            self.calls.append(deadline_monotonic)
            raise TypeError("internal type error")

    executor = TypeErrorToolExecutor()
    orchestrator = LangGraphAgentOrchestrator(engine)

    with pytest.raises(TypeError, match="internal type error"):
        orchestrator.run(
            AgentOrchestrationRequest(
                user_input="hello",
                tool_executor=executor,
                deadline_monotonic=time.monotonic() + 30.0,
            )
        )

    assert len(executor.calls) == 1
    assert executor.calls[0] is not None

