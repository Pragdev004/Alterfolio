from __future__ import annotations

SYMBOL_PATTERN = r"^[A-Z0-9.\-&]{1,20}$"

PORTFOLIO_TOOL = {
    "type": "function",
    "name": "get_portfolio_summary",
    "description": (
        "Retrieve the authenticated user's portfolio summary, including holdings, "
        "total invested amount, and total trades."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}

MARKET_TOOL = {
    "type": "function",
    "name": "get_stock_quote",
    "description": "Retrieve the latest market quote for a stock.",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "minLength": 1,
                "maxLength": 20,
                "pattern": SYMBOL_PATTERN,
                "description": "Stock symbol, uppercase, max 20 chars.",
            }
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
}

NEWS_TOOL = {
    "type": "function",
    "name": "get_company_news",
    "description": "Retrieve recent news articles for a company.",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "minLength": 1,
                "maxLength": 20,
                "pattern": SYMBOL_PATTERN,
                "description": "Stock symbol, uppercase, max 20 chars.",
            }
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
}

TOOLS = [PORTFOLIO_TOOL, MARKET_TOOL, NEWS_TOOL]
ALLOWED_TOOL_NAMES = {tool["name"] for tool in TOOLS}