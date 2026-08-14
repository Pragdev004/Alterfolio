from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.dependencies.ai import get_agent_orchestrator
from app.api.dependencies.auth import get_astra_authenticated_principal
from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.position_repository import PositionRepository
from app.services.ai.agent_orchestrator import IAgentOrchestrator
from app.services.ai.astra_query_service import AstraQueryService
from app.services.ai.tool_executor import ToolExecutor
from app.services.ai.tool_registry import ToolRegistry
from app.services.authenticated_principal import AuthenticatedPrincipal
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService


def build_astra_tool_executor(
    *,
    db: Session,
    principal: AuthenticatedPrincipal,
    settings: Settings,
) -> ToolExecutor:
    portfolio_repository = PortfolioRepository(db)
    position_repository = PositionRepository(db)
    portfolio_service = PortfolioService(
        portfolio_repository=portfolio_repository,
        position_repository=position_repository,
        market_service=MarketService(),
    )
    market_service = MarketService()
    news_service = NewsService()

    tool_registry = ToolRegistry(
        portfolio_service=portfolio_service,
        market_service=market_service,
        news_service=news_service,
        user_id=principal.user_id,
    )

    return ToolExecutor(
        tool_registry=tool_registry,
        external_call_timeout_seconds=float(settings.astra_execution_timeout_seconds),
        symbol_max_length=settings.astra_symbol_max_chars,
    )


def get_astra_tool_executor(
    db: Session = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_astra_authenticated_principal),
    settings: Settings = Depends(get_settings),
) -> ToolExecutor:
    return build_astra_tool_executor(
        db=db,
        principal=principal,
        settings=settings,
    )


def get_astra_query_service(
    orchestrator: IAgentOrchestrator = Depends(get_agent_orchestrator),
    settings: Settings = Depends(get_settings),
) -> AstraQueryService:
    return AstraQueryService(
        orchestrator=orchestrator,
        query_max_chars=settings.astra_query_max_chars,
        answer_max_chars=settings.astra_answer_max_chars,
        execution_timeout_seconds=float(settings.astra_execution_timeout_seconds),
    )
