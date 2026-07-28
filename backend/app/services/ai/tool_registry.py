from app.services.ai.tools import (
    MarketTool,
    NewsTool,
    PortfolioTool,
)
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService


class ToolRegistry:
    """
    Central registry for all AI tools.
    """

    def __init__(
        self,
        portfolio_service: PortfolioService,
        market_service: MarketService,
        news_service: NewsService,
    ) -> None:
        self.portfolio = PortfolioTool(
            portfolio_service,
        )

        self.market = MarketTool(
            market_service,
        )

        self.news = NewsTool(
            news_service,
        )