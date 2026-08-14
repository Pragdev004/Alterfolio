from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.services.ai.agent_orchestrator import AgentOrchestrationRequest, IAgentOrchestrator
from app.services.ai.tool_executor import (
    AstraTimeoutError,
    ExternalDependencyError,
    GuardrailViolationError,
    PortfolioScopeForbiddenError,
    ToolExecutor,
    ToolNotAllowedError,
)
from app.services.authenticated_principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)

TRUNCATION_MARKER = "\n\n[TRUNCATED]"


@dataclass(frozen=True)
class AstraQueryResult:
    answer: str
    agent_run_id: UUID


class AstraServiceError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        agent_run_id: UUID,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.agent_run_id = agent_run_id


class AstraQueryService:
    def __init__(
        self,
        *,
        orchestrator: IAgentOrchestrator,
        tool_executor: ToolExecutor | None = None,
        query_max_chars: int = 4000,
        answer_max_chars: int = 12000,
        execution_timeout_seconds: float = 45.0,
    ) -> None:
        self._orchestrator = orchestrator
        self._tool_executor = tool_executor
        self._query_max_chars = query_max_chars
        self._answer_max_chars = answer_max_chars
        self._execution_timeout_seconds = execution_timeout_seconds

    def execute(
        self,
        *,
        query: str,
        principal: AuthenticatedPrincipal,
        tool_executor: ToolExecutor | None = None,
    ) -> AstraQueryResult:
        agent_run_id = uuid4()
        started_monotonic = time.monotonic()

        if not isinstance(principal, AuthenticatedPrincipal) or not isinstance(principal.user_id, UUID):
            raise AstraServiceError(
                code="invalid_authenticated_principal",
                message="Invalid authenticated principal",
                status_code=401,
                agent_run_id=agent_run_id,
            )

        try:
            normalized_query = self._normalize_query(query)
        except ValueError as exc:
            raise AstraServiceError(
                code="guardrail_violation",
                message="Invalid query",
                status_code=400,
                agent_run_id=agent_run_id,
            ) from exc

        if self._is_transaction_request(normalized_query):
            raise AstraServiceError(
                code="guardrail_violation",
                message="Transaction requests are not supported",
                status_code=400,
                agent_run_id=agent_run_id,
            )

        deadline = started_monotonic + self._execution_timeout_seconds

        logger.info(
            "astra.query.start",
            extra={
                "agent_run_id": str(agent_run_id),
                "route": "/astra/query",
                "input_length": len(normalized_query),
                "status": "started",
            },
        )

        resolved_tool_executor = tool_executor or self._tool_executor
        if resolved_tool_executor is None:
            raise AstraServiceError(
                code="astra_internal_error",
                message="Internal ASTRA error",
                status_code=500,
                agent_run_id=agent_run_id,
            )

        try:
            result = self._orchestrator.run(
                AgentOrchestrationRequest(
                    user_input=normalized_query,
                    tool_executor=resolved_tool_executor,
                    agent_run_id=str(agent_run_id),
                    deadline_monotonic=deadline,
                )
            )
            self._ensure_not_expired(deadline)
            output = self._normalize_answer(result.output_text)
            portfolio_summary = getattr(result, "portfolio_summary", None)
            if portfolio_summary is None:
                portfolio_summary = getattr(resolved_tool_executor, "portfolio_summary", None)
            output = self._apply_empty_portfolio_note(output, portfolio_summary)

            logger.info(
                "astra.query.success",
                extra={
                    "agent_run_id": str(agent_run_id),
                    "route": "/astra/query",
                    "status": "success",
                    "output_length": len(output),
                    "elapsed_ms": int((time.monotonic() - started_monotonic) * 1000),
                },
            )
            return AstraQueryResult(answer=output, agent_run_id=agent_run_id)
        except AstraServiceError:
            raise
        except AstraTimeoutError as exc:
            raise AstraServiceError(
                code="astra_timeout",
                message="ASTRA request timed out",
                status_code=504,
                agent_run_id=agent_run_id,
            ) from exc
        except ToolNotAllowedError as exc:
            raise AstraServiceError(
                code="tool_not_allowed",
                message="Tool is not allowed",
                status_code=403,
                agent_run_id=agent_run_id,
            ) from exc
        except PortfolioScopeForbiddenError as exc:
            raise AstraServiceError(
                code="portfolio_scope_forbidden",
                message="Portfolio scope access is forbidden",
                status_code=403,
                agent_run_id=agent_run_id,
            ) from exc
        except GuardrailViolationError as exc:
            raise AstraServiceError(
                code="guardrail_violation",
                message="Request violates safety guardrails",
                status_code=400,
                agent_run_id=agent_run_id,
            ) from exc
        except ExternalDependencyError as exc:
            code_to_status = {
                "portfolio_tool_failed": 502,
                "market_tool_failed": 502,
                "news_tool_failed": 502,
            }
            raise AstraServiceError(
                code=exc.code,
                message="A required upstream dependency failed",
                status_code=code_to_status.get(exc.code, 502),
                agent_run_id=agent_run_id,
            ) from exc
        except RuntimeError as exc:
            message = str(exc)
            if "maximum reasoning iterations" in message or "maximum tool calls" in message:
                raise AstraServiceError(
                    code="agent_limit_exceeded",
                    message="Agent execution limit exceeded",
                    status_code=502,
                    agent_run_id=agent_run_id,
                ) from exc
            if (
                "timed out" in message.lower()
                or "mandatory portfolio grounding" in message.lower()
                or "portfolio grounding is required" in message.lower()
            ):
                if "timed out" in message.lower():
                    raise AstraServiceError(
                        code="astra_timeout",
                        message="ASTRA request timed out",
                        status_code=504,
                        agent_run_id=agent_run_id,
                    ) from exc
                raise AstraServiceError(
                    code="guardrail_violation",
                    message="Request violates safety guardrails",
                    status_code=400,
                    agent_run_id=agent_run_id,
                ) from exc
            raise AstraServiceError(
                code="model_provider_failed",
                message="Model provider failed",
                status_code=502,
                agent_run_id=agent_run_id,
            ) from exc
        except ValueError as exc:
            message = str(exc)
            if "empty model response" in message.lower():
                raise AstraServiceError(
                    code="empty_model_response",
                    message="Model returned an empty response",
                    status_code=502,
                    agent_run_id=agent_run_id,
                ) from exc
            if "malformed" in message.lower() or "missing id" in message.lower() or "response id" in message.lower():
                raise AstraServiceError(
                    code="model_provider_failed",
                    message="Model provider returned an invalid response",
                    status_code=502,
                    agent_run_id=agent_run_id,
                ) from exc
            raise AstraServiceError(
                code="astra_internal_error",
                message="Internal ASTRA error",
                status_code=500,
                agent_run_id=agent_run_id,
            ) from exc
        except Exception as exc:
            logger.error(
                "astra.query.failure",
                extra={
                    "agent_run_id": str(agent_run_id),
                    "route": "/astra/query",
                    "status": "failure",
                    "error_code": "astra_internal_error",
                    "exception_class": exc.__class__.__name__,
                },
            )
            raise AstraServiceError(
                code="astra_internal_error",
                message="Internal ASTRA error",
                status_code=500,
                agent_run_id=agent_run_id,
            ) from exc

    def _normalize_query(self, query: str) -> str:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be empty")
        if "\x00" in normalized:
            raise ValueError("query contains invalid characters")
        if len(normalized) > self._query_max_chars:
            raise ValueError("query exceeds maximum length")
        return normalized

    @staticmethod
    def _is_transaction_request(query: str) -> bool:
        lowered = query.lower()
        markers = ["buy ", "sell ", "place order", "execute trade", "rebalance"]
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _ensure_not_expired(deadline_monotonic: float) -> None:
        if time.monotonic() >= deadline_monotonic:
            raise AstraTimeoutError()

    def _normalize_answer(self, answer: str) -> str:
        text = (answer or "").strip()
        if not text:
            raise ValueError("empty model response")
        if len(text) > self._answer_max_chars:
            allowed = self._answer_max_chars - len(TRUNCATION_MARKER)
            return text[:allowed].rstrip() + TRUNCATION_MARKER
        return text

    def _apply_empty_portfolio_note(self, answer: str, portfolio_summary: object | None) -> str:
        if portfolio_summary is None:
            return answer

        holdings = getattr(portfolio_summary, "holdings", None)
        if isinstance(holdings, list) and len(holdings) == 0:
            lower_answer = answer.lower()
            if "no holdings" not in lower_answer:
                return f"{answer}\n\nNo holdings are currently available in your portfolio."
        return answer
