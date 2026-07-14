from pydantic import BaseModel

from app.schemas.portfolio import PortfolioSummary
from app.schemas.stock import StockQuote


class PortfolioAnalysisInput(BaseModel):
    portfolio: PortfolioSummary
    quotes: list[StockQuote]