from yfinance import Ticker

from app.schemas.stock import StockQuote


class MarketService:
    """
    Service responsible for retrieving live market data.
    """

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Convert internal stock symbols to Yahoo Finance symbols.
        """
        if "." not in symbol:
            return f"{symbol}.NS"

        return symbol

    def get_stock_quote(
        self,
        symbol: str,
    ) -> StockQuote:
        """
        Returns the latest market quote for a stock.
        """
        yahoo_symbol = self._normalize_symbol(symbol)
        ticker = Ticker(yahoo_symbol)
        info = ticker.info

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

        change = info.get("regularMarketChange")
        if change is None and current_price is not None and previous_close is not None:
            change = current_price - previous_close

        change_percent = info.get("regularMarketChangePercent")
        if change_percent is None and change is not None and previous_close not in (None, 0):
            change_percent = (change / previous_close) * 100

        return StockQuote(
            symbol=symbol,
            company_name=info.get("longName") or info.get("shortName") or symbol,
            current_price=float(current_price or 0.0),
            currency=info.get("currency") or "",
            change=float(change or 0.0),
            change_percent=float(change_percent or 0.0),
            day_high=float(info.get("dayHigh") or info.get("regularMarketDayHigh") or 0.0),
            day_low=float(info.get("dayLow") or info.get("regularMarketDayLow") or 0.0),
            previous_close=float(previous_close or 0.0),
            market_state=info.get("marketState") or info.get("quoteType") or "",
        )