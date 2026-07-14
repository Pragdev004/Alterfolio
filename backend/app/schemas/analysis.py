from pydantic import BaseModel

from app.schemas.news import CompanyNews
from app.schemas.portfolio import PortfolioSummary
from app.schemas.stock import StockQuote


class PortfolioAnalysisInput(BaseModel):
    portfolio: PortfolioSummary
    quotes: list[StockQuote]
    news: list[CompanyNews]