from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import get_settings
from app.services.ai.client import get_ai_client
from app.services.ai.prompts import SYSTEM_PROMPT, build_portfolio_analysis_prompt
from app.schemas.ai import PortfolioAnalysis, PortfolioAnalysisResponse
from app.schemas.portfolio import PortfolioSummary


class AIService:
    """
    Astra AI service responsible for orchestrating AI requests.
    """

    def __init__(self) -> None:
        self._client = get_ai_client()
        self._settings = get_settings()

    def analyze_portfolio(
            self, 
            portfolio_summary: PortfolioSummary
            ) -> PortfolioAnalysisResponse:
        prompt = build_portfolio_analysis_prompt(portfolio_summary)

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


ai_service = AIService()