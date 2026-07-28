from app.schemas.news import CompanyNews
from app.services.news_service import NewsService


class NewsTool:
    """
    AI tool for retrieving company news.
    """

    def __init__(
        self,
        news_service: NewsService,
    ) -> None:
        self._news_service = news_service

    def get_company_news(
        self,
        symbol: str,
    ) -> CompanyNews:
        """
        Returns recent news for a company.
        """
        return self._news_service.get_company_news(symbol)