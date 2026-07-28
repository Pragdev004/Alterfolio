from app.schemas.stock import StockQuote
from app.services.market_service import MarketService


class MarketTool:
    """
    AI tool for retrieving live market quotes.
    """

    def __init__(
        self,
        market_service: MarketService,
    ) -> None:
        self._market_service = market_service

    def get_stock_quote(
        self,
        symbol: str,
    ) -> StockQuote:
        """
        Returns the latest quote for a stock.
        """
        return self._market_service.get_stock_quote(symbol)