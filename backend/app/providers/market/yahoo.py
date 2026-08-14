from yfinance import Ticker

from app.providers.market.base import BaseMarketProvider
from app.schemas.stock import StockQuote


class YahooMarketProvider(BaseMarketProvider):
    """
    Yahoo Finance implementation.
    """

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Convert internal stock symbols to Yahoo Finance symbols.
        """
        if "." not in symbol:
            return f"{symbol}.NS"

        return symbol

    def _normalize_metadata_symbol(self, symbol: str | None) -> str | None:
        if not isinstance(symbol, str):
            return None

        normalized = symbol.strip().upper()
        return normalized or None

    def _extract_provider_symbol(self, info: dict) -> str | None:
        for key in ("symbol", "underlyingSymbol"):
            candidate = self._normalize_metadata_symbol(info.get(key))
            if candidate is not None:
                return candidate

        return None

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

        provider_symbol = self._extract_provider_symbol(info)

        return StockQuote(
            symbol=provider_symbol or "",
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
