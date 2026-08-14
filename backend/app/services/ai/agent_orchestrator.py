from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ToolExecutorPort(Protocol):
    """Application-safe executor contract used by the orchestrator."""

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        deadline_monotonic: float | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class PortfolioSummaryView:
    """Minimal application-safe projection of portfolio grounding output."""

    holdings: list[object]


@dataclass(frozen=True)
class AgentOrchestrationRequest:
    """Application-safe request DTO for agent orchestration."""

    user_input: str
    tool_executor: ToolExecutorPort | None = None
    agent_run_id: str | None = None
    deadline_monotonic: float | None = None


@dataclass(frozen=True)
class AgentOrchestrationResult:
    """Application-safe result DTO for agent orchestration."""

    output_text: str
    agent_run_id: str
    portfolio_summary: PortfolioSummaryView | None = None


class IAgentOrchestrator(Protocol):
    """Application-facing orchestration abstraction."""

    def run(
        self,
        request: AgentOrchestrationRequest,
    ) -> AgentOrchestrationResult:
        """Run Astra reasoning and return application-safe output."""
