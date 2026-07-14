from app.schemas.news import CompanyNews


class NewsService:
    """
    Retrieves recent news related to companies.
    """

    def get_company_news(
        self,
        symbol: str,
    ) -> CompanyNews:
        raise NotImplementedError