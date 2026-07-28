from app.schemas.ai import PortfolioAnalysisResponse
from app.schemas.analysis import PortfolioAnalysisInput
from app.schemas.news import CompanyNews
from app.schemas.portfolio import PortfolioSummary
from app.schemas.stock import StockQuote
from app.services.ai.ai_service import AIService
from app.services.ai.tool_registry import ToolRegistry


class PortfolioRetrievalError(Exception):
    pass


class MarketDataRetrievalError(Exception):
    pass


class AIProviderError(Exception):
    pass


class AIWorkflowService:
    """Orchestrates AI-powered workflows."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        ai_service: AIService,
    ) -> None:
        self._tools = tool_registry
        self._ai_service = ai_service

    def analyze_portfolio(self) -> PortfolioAnalysisResponse:
        try:
            summary: PortfolioSummary = (
                self._tools.portfolio.get_portfolio_summary()
            )
        except Exception as exc:
            raise PortfolioRetrievalError(
                "Failed to retrieve portfolio summary"
            ) from exc

        quotes: list[StockQuote] = []
        news: list[CompanyNews] = []

        for holding in summary.holdings:
            try:
                quotes.append(
                    self._tools.market.get_stock_quote(holding.symbol)
                )
            except Exception:
                pass

            try:
                news.append(
                    self._tools.news.get_company_news(holding.symbol)
                )
            except Exception:
                pass

        analysis_input = PortfolioAnalysisInput(
            portfolio=summary,
            quotes=quotes,
            news=news,
        )

        try:
            return self._ai_service.analyze_portfolio(analysis_input)
        except Exception as exc:
            raise AIProviderError(
                "Failed to generate portfolio analysis"
            ) from exc