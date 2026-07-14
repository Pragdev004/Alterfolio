from pydantic import BaseModel


class StockQuote(BaseModel):
    """
    Represents the current market information for a single stock.
    """

    symbol: str
    company_name: str

    current_price: float
    currency: str

    change: float
    change_percent: float

    day_high: float
    day_low: float

    previous_close: float

    market_state: str