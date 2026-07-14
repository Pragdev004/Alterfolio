from app.schemas.portfolio import PortfolioSummary
from app.services.ai.ai_service import AIService
from app.services.portfolio_service import PortfolioService
from app.schemas.ai import PortfolioAnalysisResponse


class AIWorkflowService:
    """
    Orchestrates AI-powered workflows.
    """

    def __init__(
        self,
        portfolio_service: PortfolioService,
        ai_service: AIService,
    ) -> None:
        self._portfolio_service = portfolio_service
        self._ai_service = ai_service

    def analyze_portfolio(self) -> PortfolioAnalysisResponse:
        summary: PortfolioSummary = self._portfolio_service.get_summary()

        return self._ai_service.analyze_portfolio(summary)