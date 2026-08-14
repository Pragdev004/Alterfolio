from app.providers.market.yahoo import YahooMarketProvider


def test_provider_exposes_symbol_from_yahoo_metadata(monkeypatch) -> None:
    captured_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, symbol: str):
            captured_symbols.append(symbol)
            self.info = {
                "symbol": "reliance.bo",
                "longName": "Reliance Industries",
                "currency": "INR",
                "currentPrice": 100,
                "previousClose": 98,
            }

    monkeypatch.setattr("app.providers.market.yahoo.Ticker", FakeTicker)

    provider = YahooMarketProvider()
    quote = provider.get_stock_quote("RELIANCE.BO")

    assert captured_symbols == ["RELIANCE.BO"]
    assert quote.symbol == "RELIANCE.BO"


def test_provider_uses_underlying_symbol_when_symbol_field_missing(monkeypatch) -> None:
    class FakeTicker:
        def __init__(self, symbol: str):
            self.info = {
                "underlyingSymbol": "infy.ns",
                "shortName": "Infosys",
                "currency": "INR",
                "regularMarketPrice": 200,
                "regularMarketPreviousClose": 190,
            }

    monkeypatch.setattr("app.providers.market.yahoo.Ticker", FakeTicker)

    provider = YahooMarketProvider()
    quote = provider.get_stock_quote("INFY.NS")

    assert quote.symbol == "INFY.NS"


def test_provider_does_not_fabricate_identity_when_metadata_missing(monkeypatch) -> None:
    class FakeTicker:
        def __init__(self, symbol: str):
            self.info = {
                "shortName": "Unknown",
                "currency": "INR",
                "regularMarketPrice": 200,
                "regularMarketPreviousClose": 190,
            }

    monkeypatch.setattr("app.providers.market.yahoo.Ticker", FakeTicker)

    provider = YahooMarketProvider()
    quote = provider.get_stock_quote("RELIANCE.NS")

    assert quote.symbol == ""
