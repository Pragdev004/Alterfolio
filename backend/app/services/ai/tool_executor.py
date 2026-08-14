from __future__ import annotations

import re
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable

from app.services.ai.tool_definitions import ALLOWED_TOOL_NAMES
from app.services.ai.tool_registry import ToolRegistry

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-&]+$")
_TOOL_WORKER_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="astra-tool")


class ToolExecutorError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolNotAllowedError(ToolExecutorError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            code="tool_not_allowed",
            message=f"Unknown tool: {tool_name}",
        )


class PortfolioScopeForbiddenError(ToolExecutorError):
    def __init__(self) -> None:
        super().__init__(
            code="portfolio_scope_forbidden",
            message="Portfolio scope arguments are forbidden",
        )


class GuardrailViolationError(ToolExecutorError):
    def __init__(self, message: str) -> None:
        super().__init__(code="guardrail_violation", message=message)


class ExternalDependencyError(ToolExecutorError):
    pass


class AstraTimeoutError(ToolExecutorError):
    def __init__(self) -> None:
        super().__init__(code="astra_timeout", message="ASTRA execution timed out")


class ToolExecutor:
    """Executes AI tool calls with strict allowlist and argument validation."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        *,
        external_call_timeout_seconds: float = 8.0,
        symbol_max_length: int = 20,
    ) -> None:
        self._tools = tool_registry
        self._external_call_timeout_seconds = external_call_timeout_seconds
        self._symbol_max_length = symbol_max_length

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        deadline_monotonic: float | None = None,
    ) -> Any:
        self._ensure_not_expired(deadline_monotonic)

        if tool_name not in ALLOWED_TOOL_NAMES:
            raise ToolNotAllowedError(tool_name)

        if not isinstance(arguments, dict):
            raise GuardrailViolationError("Tool arguments must be an object")

        if tool_name == "get_portfolio_summary":
            self._validate_portfolio_arguments(arguments)
            result = self._invoke_with_budget(
                self._tools.portfolio.get_portfolio_summary,
                deadline_monotonic,
                error_code="portfolio_tool_failed",
                error_message="Portfolio tool failed",
            )
            self._ensure_not_expired(deadline_monotonic)
            return result

        symbol = self._extract_symbol(arguments)

        if tool_name == "get_stock_quote":
            result = self._invoke_with_budget(
                lambda: self._tools.market.get_stock_quote(symbol),
                deadline_monotonic,
                error_code="market_tool_failed",
                error_message="Market tool failed",
            )
            self._ensure_not_expired(deadline_monotonic)
            return result

        if tool_name == "get_company_news":
            result = self._invoke_with_budget(
                lambda: self._tools.news.get_company_news(symbol),
                deadline_monotonic,
                error_code="news_tool_failed",
                error_message="News tool failed",
            )
            self._ensure_not_expired(deadline_monotonic)
            return result

        raise ToolNotAllowedError(tool_name)

    def _validate_portfolio_arguments(self, arguments: dict[str, Any]) -> None:
        if any(key in arguments for key in ("user_id", "portfolio_id")):
            raise PortfolioScopeForbiddenError()
        if arguments != {}:
            raise GuardrailViolationError("get_portfolio_summary requires empty arguments")

    def _extract_symbol(self, arguments: dict[str, Any]) -> str:
        if any(key in arguments for key in ("user_id", "portfolio_id")):
            raise PortfolioScopeForbiddenError()

        if set(arguments.keys()) != {"symbol"}:
            raise GuardrailViolationError("Tool arguments must contain only 'symbol'")

        symbol = arguments.get("symbol")
        if not isinstance(symbol, str):
            raise GuardrailViolationError("symbol must be a string")

        normalized = symbol.strip().upper()
        if not normalized:
            raise GuardrailViolationError("symbol must not be empty")
        if len(normalized) > self._symbol_max_length:
            raise GuardrailViolationError("symbol exceeds maximum length")
        if not _SYMBOL_RE.fullmatch(normalized):
            raise GuardrailViolationError("symbol contains invalid characters")

        return normalized

    def _invoke_with_budget(
        self,
        func: Callable[[], Any],
        deadline_monotonic: float | None,
        *,
        error_code: str,
        error_message: str,
    ) -> Any:
        timeout_seconds = self._compute_timeout(deadline_monotonic)
        future: Future[Any] = _TOOL_WORKER_POOL.submit(func)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise AstraTimeoutError() from exc
        except ToolExecutorError:
            raise
        except Exception as exc:
            raise ExternalDependencyError(code=error_code, message=error_message) from exc

    def _compute_timeout(self, deadline_monotonic: float | None) -> float:
        if deadline_monotonic is None:
            return self._external_call_timeout_seconds

        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise AstraTimeoutError()

        return min(self._external_call_timeout_seconds, remaining)

    @staticmethod
    def _ensure_not_expired(deadline_monotonic: float | None) -> None:
        if deadline_monotonic is None:
            return
        if time.monotonic() >= deadline_monotonic:
            raise AstraTimeoutError()
