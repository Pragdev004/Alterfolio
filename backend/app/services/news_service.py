from app.providers.news.yahoo import YahooNewsProvider
from app.schemas.news import CompanyNews


class NewsService:
    """
    Retrieves recent news related to companies.
    """

    def __init__(self) -> None:
        self._provider = YahooNewsProvider()

    def get_company_news(
        self,
        symbol: str,
    ) -> CompanyNews:
        return self._provider.get_company_news(symbol)