from app.services.market_service import MarketService


if __name__ == "__main__":
    service = MarketService()
    quote = service.get_stock_quote("RELIANCE.NS")
    print(quote)