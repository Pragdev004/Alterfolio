from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.repositories.portfolio_repository import PortfolioRepository
from app.schemas.portfolio import PortfolioSummary
from app.services.portfolio_service import PortfolioService
from app.services.ai.ai_service import AIService
from app.services.ai.workflow_service import AIWorkflowService

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
):
    return service.get_summary()

def get_ai_workflow_service(
    db: Session = Depends(get_db),
) -> AIWorkflowService:
    repository = PortfolioRepository(db)

    portfolio_service = PortfolioService(repository)

    ai_service = AIService()

    return AIWorkflowService(
        portfolio_service=portfolio_service,
        ai_service=ai_service,
    )

@router.get(
    "/analysis",
    summary="Analyze portfolio using Astra AI",
)
def analyze_portfolio(
    workflow: AIWorkflowService = Depends(get_ai_workflow_service),
):
    return workflow.analyze_portfolio()