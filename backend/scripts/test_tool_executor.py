from app.db.database import SessionLocal
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.ai.tool_executor import ToolExecutor
from app.services.ai.tool_registry import ToolRegistry
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService


db = SessionLocal()

try:
    repository = PortfolioRepository(db)

    portfolio_service = PortfolioService(repository)
    market_service = MarketService()
    news_service = NewsService()

    registry = ToolRegistry(
        portfolio_service=portfolio_service,
        market_service=market_service,
        news_service=news_service,
    )

    executor = ToolExecutor(registry)

    print("=" * 80)
    print("PORTFOLIO")
    print("=" * 80)
    print(executor.execute("get_portfolio_summary", {}))

    print("\n" + "=" * 80)
    print("MARKET")
    print("=" * 80)
    print(
        executor.execute(
            "get_stock_quote",
            {"symbol": "RELIANCE"},
        )
    )

    print("\n" + "=" * 80)
    print("NEWS")
    print("=" * 80)
    print(
        executor.execute(
            "get_company_news",
            {"symbol": "RELIANCE"},
        )
    )

finally:
    db.close()