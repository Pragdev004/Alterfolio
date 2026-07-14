from enum import Enum


class AssetType(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    MUTUAL_FUND = "MUTUAL_FUND"
    BOND = "BOND"
    GOLD = "GOLD"
    REIT = "REIT"
    INVIT = "INVIT"
    INDEX = "INDEX"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"
    CASH = "CASH"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSource(str, Enum):
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"
    BROKER_SYNC = "BROKER_SYNC"
    AI = "AI"


class MarketSession(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    POST_MARKET = "POST_MARKET"


class InvestmentHorizon(str, Enum):
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class Currency(str, Enum):
    INR = "INR"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    MCX = "MCX"