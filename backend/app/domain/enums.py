from enum import Enum


class AssetType(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class Currency(str, Enum):
    INR = "INR"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    EXECUTED = "EXECUTED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TradeSource(str, Enum):
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class MarketSession(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    POST_MARKET = "POST_MARKET"
