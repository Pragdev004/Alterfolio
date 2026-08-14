from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies.ai import get_structured_ai_service
from app.api.dependencies.auth import get_authenticated_user_id
from app.db.database import get_db
from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.ai import ErrorResponse, PortfolioAnalysisResponse
from app.schemas.portfolio import PortfolioSummary
from app.services.ai.ai_service import AIService
from app.services.ai.tool_registry import ToolRegistry
from app.services.ai.workflow_service import (
    AIProviderError,
    AIWorkflowService,
    MarketDataRetrievalError,
    PortfolioRetrievalError,
)
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService

router = APIRouter()


def get_portfolio_service(
    db: Session = Depends(get_db),
) -> PortfolioService:
    repository = PortfolioRepository(db)
    return PortfolioService(repository)


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Get portfolio summary",
)
def get_portfolio_summary(
    service: PortfolioService = Depends(get_portfolio_service),
    user_id: UUID = Depends(get_authenticated_user_id),
):
    return service.get_summary(user_id)


def get_ai_workflow_service(
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_authenticated_user_id),
    ai_service: AIService = Depends(get_structured_ai_service),
) -> AIWorkflowService:
    repository = PortfolioRepository(db)

    portfolio_service = PortfolioService(repository)
    market_service = MarketService()
    news_service = NewsService()

    tool_registry = ToolRegistry(
        portfolio_service=portfolio_service,
        market_service=market_service,
        news_service=news_service,
        user_id=user_id,
    )

    return AIWorkflowService(
        tool_registry=tool_registry,
        ai_service=ai_service,
    )


@router.get(
    "/analysis",
    response_model=PortfolioAnalysisResponse,
    summary="Analyze portfolio using Astra AI",
    responses={
        500: {
            "model": ErrorResponse,
            "description": "Portfolio retrieval failure",
        },
        502: {
            "model": ErrorResponse,
            "description": "Market data or AI provider failure",
        },
    },
)
def analyze_portfolio(
    workflow: AIWorkflowService = Depends(get_ai_workflow_service),
):
    try:
        return workflow.analyze_portfolio()
    except PortfolioRetrievalError as exc:
        return JSONResponse(
            status_code=500,
            content={
                "code": "portfolio_retrieval_failed",
                "message": str(exc),
            },
        )
    except MarketDataRetrievalError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "code": "market_data_retrieval_failed",
                "message": str(exc),
            },
        )
    except AIProviderError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "code": "ai_provider_failed",
                "message": str(exc),
            },
        )