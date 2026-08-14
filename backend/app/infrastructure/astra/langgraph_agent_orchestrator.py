from __future__ import annotations

import time
from typing import Protocol, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.infrastructure.astra.reasoning_types import (
    ReasoningToolCall,
    ReasoningToolResult,
    ReasoningTurn,
)
from app.services.ai.agent_orchestrator import (
    AgentOrchestrationRequest,
    AgentOrchestrationResult,
    IAgentOrchestrator,
    PortfolioSummaryView,
    ToolExecutorPort,
)
from app.services.ai.tool_executor import GuardrailViolationError


class _AstraGraphState(TypedDict, total=False):
    user_input: str
    tool_executor: ToolExecutorPort
    output_text: str
    agent_run_id: str
    pending_tool_calls: list[ReasoningToolCall]
    tool_results: list[ReasoningToolResult]
    previous_response_id: str
    iteration_count: int
    tool_call_count: int
    deadline_monotonic: float
    portfolio_grounded: bool
    portfolio_summary: PortfolioSummaryView | None


class _ReasoningEngine(Protocol):
    def initial_reasoning(
        self,
        *,
        user_input: str,
        include_tools: bool,
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn: ...

    def followup_reasoning(
        self,
        *,
        previous_response_id: str,
        tool_results: list[ReasoningToolResult],
        deadline_monotonic: float | None = None,
    ) -> ReasoningTurn: ...


class LangGraphAgentOrchestrator(IAgentOrchestrator):
    """LangGraph-backed adapter implementing Astra orchestration boundary."""

    def __init__(
        self,
        reasoning_engine: _ReasoningEngine,
        *,
        max_iterations: int = 8,
        max_tool_calls: int = 20,
        require_portfolio_grounding: bool = False,
    ) -> None:
        self._reasoning_engine = reasoning_engine
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls
        self._require_portfolio_grounding = require_portfolio_grounding
        self._graph = self._build_graph()

    @staticmethod
    def _ensure_not_expired(deadline_monotonic: float | None) -> None:
        if deadline_monotonic is None:
            return
        if time.monotonic() >= deadline_monotonic:
            raise RuntimeError("ASTRA execution timed out")

    def _build_graph(self):
        graph = StateGraph(_AstraGraphState)
        graph.add_node("astra_reasoning", self._astra_reasoning_node)
        graph.add_node("astra_tool_execution", self._astra_tool_node)
        graph.add_edge(START, "astra_reasoning")
        graph.add_conditional_edges(
            "astra_reasoning",
            self._route_after_reasoning,
            {
                "astra_tool_execution": "astra_tool_execution",
                "end": END,
            },
        )
        graph.add_edge("astra_tool_execution", "astra_reasoning")
        return graph.compile()

    @staticmethod
    def _get_tool_executor(config: RunnableConfig | None) -> ToolExecutorPort | None:
        if config is None:
            return None
        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return None
        tool_executor = configurable.get("tool_executor")
        if tool_executor is None:
            return None
        return tool_executor

    def _route_after_reasoning(self, state: _AstraGraphState) -> str:
        if state.get("pending_tool_calls"):
            return "astra_tool_execution"

        if (
            self._require_portfolio_grounding
            and state.get("tool_executor") is not None
            and not state.get("portfolio_grounded", False)
        ):
            raise GuardrailViolationError("Mandatory portfolio grounding not satisfied")

        return "end"

    def _astra_reasoning_node(
        self,
        state: _AstraGraphState,
        config: RunnableConfig | None = None,
    ) -> _AstraGraphState:
        deadline_monotonic = state.get("deadline_monotonic")
        self._ensure_not_expired(deadline_monotonic)

        iteration_count = state.get("iteration_count", 0) + 1
        if iteration_count > self._max_iterations:
            raise RuntimeError("Exceeded maximum reasoning iterations")

        tool_results = state.get("tool_results") or []
        tool_executor = self._get_tool_executor(config) or state.get("tool_executor")

        if tool_results:
            turn = self._reasoning_engine.followup_reasoning(
                previous_response_id=state["previous_response_id"],
                tool_results=tool_results,
                deadline_monotonic=deadline_monotonic,
            )
        else:
            turn = self._reasoning_engine.initial_reasoning(
                user_input=state["user_input"],
                include_tools=tool_executor is not None,
                deadline_monotonic=deadline_monotonic,
            )

        self._ensure_not_expired(deadline_monotonic)

        updates: _AstraGraphState = {
            "output_text": turn.output_text,
            "pending_tool_calls": turn.tool_calls,
            "tool_results": [],
            "iteration_count": iteration_count,
            "agent_run_id": state["agent_run_id"],
            "deadline_monotonic": deadline_monotonic,
        }

        if turn.tool_calls:
            if not turn.response_id:
                raise ValueError("Reasoning turn missing response id")
            updates["previous_response_id"] = turn.response_id

        return updates

    def _astra_tool_node(
        self,
        state: _AstraGraphState,
        config: RunnableConfig | None = None,
    ) -> _AstraGraphState:
        deadline_monotonic = state.get("deadline_monotonic")
        self._ensure_not_expired(deadline_monotonic)

        tool_executor = self._get_tool_executor(config) or state.get("tool_executor")
        if tool_executor is None:
            raise ValueError("Tool executor is required for tool calls")

        pending_tool_calls = state.get("pending_tool_calls") or []
        tool_call_count = state.get("tool_call_count", 0)

        tool_results: list[ReasoningToolResult] = []
        portfolio_grounded = state.get("portfolio_grounded", False)
        portfolio_summary = state.get("portfolio_summary")

        for call in pending_tool_calls:
            if tool_call_count >= self._max_tool_calls:
                raise RuntimeError("Exceeded maximum tool calls")

            if self._require_portfolio_grounding and not portfolio_grounded and call.name != "get_portfolio_summary":
                raise GuardrailViolationError(
                    "Portfolio grounding is required before non-portfolio tools"
                )

            result = tool_executor.execute(
                call.name,
                call.arguments,
                deadline_monotonic=deadline_monotonic,
            )

            tool_call_count += 1

            if call.name == "get_portfolio_summary":
                portfolio_grounded = True
                portfolio_summary = self._to_portfolio_summary_view(result)

            tool_results.append(
                ReasoningToolResult(
                    call_id=call.call_id,
                    result=result,
                )
            )

        self._ensure_not_expired(deadline_monotonic)

        return {
            "tool_results": tool_results,
            "pending_tool_calls": [],
            "tool_call_count": tool_call_count,
            "agent_run_id": state["agent_run_id"],
            "deadline_monotonic": deadline_monotonic,
            "portfolio_grounded": portfolio_grounded,
            "portfolio_summary": portfolio_summary,
        }

    @staticmethod
    def _to_portfolio_summary_view(result: object) -> PortfolioSummaryView | None:
        holdings: object | None = None

        if isinstance(result, dict):
            holdings = result.get("holdings")
        else:
            holdings = getattr(result, "holdings", None)

        if isinstance(holdings, list):
            return PortfolioSummaryView(holdings=list(holdings))

        return None

    def run(
        self,
        request: AgentOrchestrationRequest,
    ) -> AgentOrchestrationResult:
        agent_run_id = request.agent_run_id or str(uuid4())
        initial_tool_call_count = 0

        final_state = self._graph.invoke(
            {
                "user_input": request.user_input,
                "agent_run_id": agent_run_id,
                "tool_executor": request.tool_executor,
                "iteration_count": 0,
                "tool_call_count": initial_tool_call_count,
                "tool_results": [],
                "deadline_monotonic": request.deadline_monotonic,
                "portfolio_grounded": False,
                "portfolio_summary": None,
            },
            config={
                "configurable": {
                    "tool_executor": request.tool_executor,
                }
            },
        )

        self._ensure_not_expired(request.deadline_monotonic)

        return AgentOrchestrationResult(
            output_text=final_state.get("output_text", ""),
            agent_run_id=final_state["agent_run_id"],
            portfolio_summary=final_state.get("portfolio_summary"),
        )
