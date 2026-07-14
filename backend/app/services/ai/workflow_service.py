from app.schemas.analysis import PortfolioAnalysisInput
from app.schemas.news import CompanyNews
from app.schemas.portfolio import PortfolioSummary
from app.schemas.stock import StockQuote
from app.services.ai.ai_service import AIService
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService
from app.schemas.ai import PortfolioAnalysisResponse


class AIWorkflowService:
    """
    Orchestrates AI-powered workflows.
    """

    def __init__(
        self,
        portfolio_service: PortfolioService,
        market_service: MarketService,
        news_service: NewsService,
        ai_service: AIService,
    ) -> None:
        self._portfolio_service = portfolio_service
        self._market_service = market_service
        self._news_service = news_service
        self._ai_service = ai_service

    def analyze_portfolio(self) -> PortfolioAnalysisResponse:
        summary: PortfolioSummary = self._portfolio_service.get_summary()

        quotes: list[StockQuote] = []
        news: list[CompanyNews] = []

        for holding in summary.holdings:
            quotes.append(
                self._market_service.get_stock_quote(holding.symbol)
            )

            news.append(
                self._news_service.get_company_news(holding.symbol)
            )

        analysis_input = PortfolioAnalysisInput(
            portfolio=summary,
            quotes=quotes,
            news=news,
        )

        return self._ai_service.analyze_portfolio(analysis_input)