from yfinance import Ticker

from app.providers.news.base import BaseNewsProvider
from app.schemas.news import CompanyNews, NewsArticle


class YahooNewsProvider(BaseNewsProvider):
    """
    Yahoo Finance implementation of the news provider.
    """

    def _normalize_symbol(
        self,
        symbol: str,
    ) -> str:
        if "." not in symbol:
            return f"{symbol}.NS"

        return symbol

    def get_company_news(
        self,
        symbol: str,
    ) -> CompanyNews:

        yahoo_symbol = self._normalize_symbol(symbol)

        ticker = Ticker(yahoo_symbol)

        news = ticker.news

        articles = []

        for article in news[:5]:

            content = article.get("content", {})

            provider = content.get("provider", {})

            canonical = content.get("canonicalUrl", {})

            articles.append(
                NewsArticle(
                    title=content.get("title", ""),
                    summary=content.get("summary", ""),
                    source=provider.get("displayName", ""),
                    url=canonical.get("url", ""),
                )
            )

        return CompanyNews(
            symbol=symbol,
            articles=articles,
        )