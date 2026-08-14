from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.config import Settings, get_settings

from app.schemas.analysis import PortfolioAnalysisInput
from app.schemas.ai import PortfolioAnalysis, PortfolioAnalysisResponse
from app.services.ai.agent_orchestrator import (
    AgentOrchestrationRequest,
    IAgentOrchestrator,
)
from app.services.ai.client import get_ai_client
from app.services.ai.prompts import SYSTEM_PROMPT, build_portfolio_analysis_prompt
from app.services.ai.tool_definitions import TOOLS

if TYPE_CHECKING:
    from app.services.ai.tool_executor import ToolExecutor


class AIServiceConfigurationError(Exception):
    """Raised when AIService is used without required runtime configuration."""


class AIService:
    """Astra AI service responsible for orchestrating AI requests."""

    def __init__(
        self,
        agent_orchestrator: IAgentOrchestrator | None = None,
        *,
        client: Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._client = client or get_ai_client()
        self._settings = settings or get_settings()
        self._agent_orchestrator = agent_orchestrator

    def analyze_portfolio(
        self,

        analysis_input: PortfolioAnalysisInput,
    ) -> PortfolioAnalysisResponse:
        prompt = build_portfolio_analysis_prompt(analysis_input)

        response = self._client.responses.parse(
            model=self._settings.azure_openai_deployment,
            instructions=SYSTEM_PROMPT,
            input=prompt,
            text_format=PortfolioAnalysis,
        )

        analysis = response.output_parsed

        return PortfolioAnalysisResponse(
            analysis=analysis,
            model=self._settings.azure_openai_deployment,
            generated_at=datetime.now(timezone.utc),
        )

    def create_tool_response(self, user_input: str):
        return self._client.responses.create(
            model=self._settings.azure_openai_deployment,
            input=user_input,
            tools=TOOLS,
        )

    def run_agent(
        self,
        user_input: str,
        executor: ToolExecutor,
    ) -> str:
        if self._agent_orchestrator is None:
            raise AIServiceConfigurationError(
                "Agent orchestrator is not configured for AIService.run_agent"
            )

        result = self._agent_orchestrator.run(
            AgentOrchestrationRequest(
                user_input=user_input,
                tool_executor=executor,
            )
        )
        return result.output_text
