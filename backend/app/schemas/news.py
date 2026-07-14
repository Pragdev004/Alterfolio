from pydantic import BaseModel


class NewsArticle(BaseModel):
    title: str
    summary: str
    source: str
    url: str


class CompanyNews(BaseModel):
    symbol: str
    articles: list[NewsArticle]