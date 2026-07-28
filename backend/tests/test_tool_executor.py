from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.ai.tool_executor import ToolExecutor


def test_execute_routes_portfolio_summary_call() -> None:
    portfolio_tool = SimpleNamespace(
        get_portfolio_summary=Mock(return_value={"total_trades": 2})
    )
    market_tool = SimpleNamespace(get_stock_quote=Mock())
    news_tool = SimpleNamespace(get_company_news=Mock())

    registry = SimpleNamespace(
        portfolio=portfolio_tool,
        market=market_tool,
        news=news_tool,
    )

    executor = ToolExecutor(registry)

    result = executor.execute("get_portfolio_summary", {})

    assert result == {"total_trades": 2}
    portfolio_tool.get_portfolio_summary.assert_called_once_with()
    market_tool.get_stock_quote.assert_not_called()
    news_tool.get_company_news.assert_not_called()


def test_execute_routes_stock_quote_call_with_symbol() -> None:
    portfolio_tool = SimpleNamespace(get_portfolio_summary=Mock())
    market_tool = SimpleNamespace(get_stock_quote=Mock(return_value={"symbol": "TCS"}))
    news_tool = SimpleNamespace(get_company_news=Mock())

    registry = SimpleNamespace(
        portfolio=portfolio_tool,
        market=market_tool,
        news=news_tool,
    )

    executor = ToolExecutor(registry)

    result = executor.execute("get_stock_quote", {"symbol": "TCS"})

    assert result == {"symbol": "TCS"}
    market_tool.get_stock_quote.assert_called_once_with("TCS")
    portfolio_tool.get_portfolio_summary.assert_not_called()
    news_tool.get_company_news.assert_not_called()


def test_execute_routes_company_news_call_with_symbol() -> None:
    portfolio_tool = SimpleNamespace(get_portfolio_summary=Mock())
    market_tool = SimpleNamespace(get_stock_quote=Mock())
    news_tool = SimpleNamespace(get_company_news=Mock(return_value={"symbol": "INFY"}))

    registry = SimpleNamespace(
        portfolio=portfolio_tool,
        market=market_tool,
        news=news_tool,
    )

    executor = ToolExecutor(registry)

    result = executor.execute("get_company_news", {"symbol": "INFY"})

    assert result == {"symbol": "INFY"}
    news_tool.get_company_news.assert_called_once_with("INFY")
    portfolio_tool.get_portfolio_summary.assert_not_called()
    market_tool.get_stock_quote.assert_not_called()


def test_execute_raises_for_unknown_tool() -> None:
    registry = SimpleNamespace(
        portfolio=SimpleNamespace(get_portfolio_summary=Mock()),
        market=SimpleNamespace(get_stock_quote=Mock()),
        news=SimpleNamespace(get_company_news=Mock()),
    )

    executor = ToolExecutor(registry)

    with pytest.raises(ValueError, match="Unknown tool: unknown_tool"):
        executor.execute("unknown_tool", {})
