from app.providers.market.yahoo import YahooMarketProvider
from app.schemas.stock import StockQuote


class MarketService:
    """
    Service responsible for retrieving live market data.
    """

    def __init__(self) -> None:
        self._provider = YahooMarketProvider()

    def get_stock_quote(
        self,
        symbol: str,
    ) -> StockQuote:
        """
        Returns the latest market quote for a stock.
        """
        return self._provider.get_stock_quote(symbol)