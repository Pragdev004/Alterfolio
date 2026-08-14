from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.tool_executor import (
    GuardrailViolationError,
    PortfolioScopeForbiddenError,
    ToolExecutor,
    ToolNotAllowedError,
)


@pytest.fixture
def executor() -> ToolExecutor:
    registry = SimpleNamespace(
        portfolio=SimpleNamespace(get_portfolio_summary=lambda: {"holdings": []}),
        market=SimpleNamespace(get_stock_quote=lambda symbol: {"symbol": symbol}),
        news=SimpleNamespace(get_company_news=lambda symbol: {"symbol": symbol, "articles": []}),
    )
    return ToolExecutor(registry)


def test_unknown_tool_rejected(executor: ToolExecutor) -> None:
    with pytest.raises(ToolNotAllowedError):
        executor.execute("delete_position", {})


def test_stock_quote_allowed_without_orchestrator_state(executor: ToolExecutor) -> None:
    result = executor.execute("get_stock_quote", {"symbol": "TCS"})
    assert result == {"symbol": "TCS"}


def test_portfolio_tool_must_have_empty_args(executor: ToolExecutor) -> None:
    with pytest.raises(GuardrailViolationError):
        executor.execute("get_portfolio_summary", {"symbol": "TCS"})


def test_extra_arguments_rejected(executor: ToolExecutor) -> None:
    executor.execute("get_portfolio_summary", {})
    with pytest.raises(GuardrailViolationError):
        executor.execute("get_stock_quote", {"symbol": "TCS", "x": 1})


def test_invalid_symbol_rejected(executor: ToolExecutor) -> None:
    executor.execute("get_portfolio_summary", {})

    with pytest.raises(GuardrailViolationError):
        executor.execute("get_stock_quote", {"symbol": " bad! "})


def test_oversized_symbol_rejected(executor: ToolExecutor) -> None:
    executor.execute("get_portfolio_summary", {})

    with pytest.raises(GuardrailViolationError):
        executor.execute("get_stock_quote", {"symbol": "A" * 21})


def test_portfolio_scope_fields_forbidden(executor: ToolExecutor) -> None:
    with pytest.raises(PortfolioScopeForbiddenError):
        executor.execute("get_portfolio_summary", {"user_id": "x"})
