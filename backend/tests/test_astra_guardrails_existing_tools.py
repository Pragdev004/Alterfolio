from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.schemas.news import CompanyNews, NewsArticle
from app.schemas.portfolio import HoldingSummary, PortfolioSummary
from app.schemas.stock import StockQuote
from app.services.ai.tool_registry import ToolRegistry
from app.services.ai.tools.market_tool import MarketTool
from app.services.ai.tools.news_tool import NewsTool
from app.services.ai.tools.portfolio_tool import PortfolioTool


class _StubPortfolioService:
    def get_summary(self, user_id):
        return PortfolioSummary(
            total_trades=1,
            total_invested=Decimal("1000"),
            holdings=[
                HoldingSummary(
                    symbol="TCS",
                    quantity=Decimal("1"),
                    average_buy_price=Decimal("1000"),
                    invested_amount=Decimal("1000"),
                )
            ],
        )


class _StubMarketService:
    def get_stock_quote(self, symbol: str) -> StockQuote:
        return StockQuote(
            symbol=symbol,
            company_name="Test Ltd",
            current_price=100.0,
            currency="INR",
            change=1.0,
            change_percent=1.0,
            day_high=101.0,
            day_low=99.0,
            previous_close=99.0,
            market_state="REGULAR",
        )


class _StubNewsService:
    def get_company_news(self, symbol: str) -> CompanyNews:
        return CompanyNews(
            symbol=symbol,
            articles=[
                NewsArticle(
                    title="title",
                    summary="summary",
                    source="source",
                    url="https://example.com",
                )
            ],
        )


def test_tool_registry_and_tools_remain_wired_without_langgraph_wrapping() -> None:
    registry = ToolRegistry(
        portfolio_service=_StubPortfolioService(),
        market_service=_StubMarketService(),
        news_service=_StubNewsService(),
        user_id=uuid4(),
    )

    assert isinstance(registry.portfolio, PortfolioTool)
    assert isinstance(registry.market, MarketTool)
    assert isinstance(registry.news, NewsTool)

    assert registry.portfolio.get_portfolio_summary().total_trades == 1
    assert registry.market.get_stock_quote("TCS").symbol == "TCS"
    assert registry.news.get_company_news("TCS").symbol == "TCS"
