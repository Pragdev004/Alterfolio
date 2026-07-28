from __future__ import annotations

from app.services.ai.tool_registry import ToolRegistry


class ToolExecutor:
    """
    Executes AI tool calls using the registered tools.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
    ) -> None:
        self._tools = tool_registry

    def execute(
        self,
        tool_name: str,
        arguments: dict,
    ):
        """
        Execute a tool call requested by the AI model.
        """

        if tool_name == "get_portfolio_summary":
            return self._tools.portfolio.get_portfolio_summary()

        if tool_name == "get_stock_quote":
            return self._tools.market.get_stock_quote(
                arguments["symbol"]
            )

        if tool_name == "get_company_news":
            return self._tools.news.get_company_news(
                arguments["symbol"]
            )

        raise ValueError(f"Unknown tool: {tool_name}")