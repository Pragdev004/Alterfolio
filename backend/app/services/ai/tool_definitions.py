from __future__ import annotations


PORTFOLIO_TOOL = {
    "type": "function",
    "name": "get_portfolio_summary",
    "description": (
        "Retrieve the user's portfolio summary, including holdings, "
        "total invested amount, and total trades."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


MARKET_TOOL = {
    "type": "function",
    "name": "get_stock_quote",
    "description": (
        "Retrieve the latest market quote for a stock."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Stock symbol, e.g. RELIANCE or TCS.",
            }
        },
        "required": ["symbol"],
    },
}


NEWS_TOOL = {
    "type": "function",
    "name": "get_company_news",
    "description": (
        "Retrieve recent news articles for a company."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Stock symbol, e.g. RELIANCE or TCS.",
            }
        },
        "required": ["symbol"],
    },
}


TOOLS = [
    PORTFOLIO_TOOL,
    MARKET_TOOL,
    NEWS_TOOL,
]