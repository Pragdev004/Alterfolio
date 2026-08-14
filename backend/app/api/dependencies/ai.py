from __future__ import annotations

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.infrastructure.astra.azure_foundry_reasoning_engine import AzureFoundryReasoningEngine
from app.infrastructure.astra.langgraph_agent_orchestrator import LangGraphAgentOrchestrator
from app.services.ai.agent_orchestrator import IAgentOrchestrator
from app.services.ai.ai_service import AIService
from app.services.ai.client import get_ai_client


def get_structured_ai_service() -> AIService:
    """AI service for structured portfolio analysis without ASTRA initialization."""
    return AIService(agent_orchestrator=None)


def get_agent_orchestrator(
    settings: Settings = Depends(get_settings),
) -> IAgentOrchestrator:
    client = get_ai_client()
    reasoning_engine = AzureFoundryReasoningEngine(
        client=client,
        model=settings.azure_openai_deployment,
        max_output_tokens=settings.astra_provider_max_output_tokens,
    )
    return LangGraphAgentOrchestrator(
        reasoning_engine=reasoning_engine,
        max_iterations=settings.astra_max_reasoning_iterations,
        max_tool_calls=settings.astra_max_cumulative_tool_calls,
        require_portfolio_grounding=True,
    )


def get_agent_ai_service(
    orchestrator: IAgentOrchestrator = Depends(get_agent_orchestrator),
) -> AIService:
    """AI service configured with ASTRA orchestration capabilities."""
    return AIService(agent_orchestrator=orchestrator)
