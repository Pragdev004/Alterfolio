from app.db.database import SessionLocal
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.ai.ai_service import AIService
from app.services.ai.tool_executor import ToolExecutor
from app.services.ai.tool_registry import ToolRegistry
from app.services.market_service import MarketService
from app.services.news_service import NewsService
from app.services.portfolio_service import PortfolioService


def main() -> None:
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
        ai_service = AIService()

        prompt = (
            "Analyze my investment portfolio. Use any available tools to retrieve "
            "my holdings, market quotes, and recent company news, then give me a "
            "clear final recommendation."
        )

        final_answer = ai_service.run_agent(prompt, executor)

        print(final_answer)

    finally:
        db.close()


if __name__ == "__main__":
    main()