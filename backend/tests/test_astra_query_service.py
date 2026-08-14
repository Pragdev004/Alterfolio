from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.ai.agent_orchestrator import AgentOrchestrationResult
from app.services.ai.astra_query_service import AstraQueryService, AstraServiceError
from app.services.ai.tool_executor import AstraTimeoutError
from app.services.authenticated_principal import AuthenticatedPrincipal


class _StubOrchestrator:
    def __init__(self, *, result_text: str = "answer", error: Exception | None = None) -> None:
        self._result_text = result_text
        self._error = error

    def run(self, request):
        if self._error:
            raise self._error
        return AgentOrchestrationResult(output_text=self._result_text, agent_run_id=request.agent_run_id)


class _StubExecutor:
    def __init__(self, holdings=None) -> None:
        self.portfolio_summary = SimpleNamespace(holdings=holdings) if holdings is not None else None


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=uuid4())


def test_transaction_guardrail() -> None:
    service = AstraQueryService(orchestrator=_StubOrchestrator(), tool_executor=_StubExecutor())

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="Please buy 10 shares of TCS", principal=_principal())

    assert exc.value.code == "guardrail_violation"
    assert exc.value.status_code == 400


def test_model_failure_maps_to_provider_failed() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(error=RuntimeError("model boom")),
        tool_executor=_StubExecutor(),
    )

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="hello", principal=_principal())

    assert exc.value.code == "model_provider_failed"
    assert exc.value.status_code == 502


def test_empty_model_response_maps_deterministically() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(result_text="   "),
        tool_executor=_StubExecutor(),
    )

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="hello", principal=_principal())

    assert exc.value.code == "empty_model_response"
    assert exc.value.status_code == 502


def test_iteration_limit_maps_to_agent_limit_exceeded() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(error=RuntimeError("Exceeded maximum reasoning iterations")),
        tool_executor=_StubExecutor(),
    )

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="hello", principal=_principal())

    assert exc.value.code == "agent_limit_exceeded"


def test_timeout_mapping() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(error=AstraTimeoutError()),
        tool_executor=_StubExecutor(),
    )

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="hello", principal=_principal())

    assert exc.value.code == "astra_timeout"
    assert exc.value.status_code == 504


def test_output_limit_truncation() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(result_text="x" * 13000),
        tool_executor=_StubExecutor(),
    )

    result = service.execute(query="hello", principal=_principal())
    assert len(result.answer) <= 12000
    assert result.answer.endswith("[TRUNCATED]")


def test_empty_portfolio_note_added() -> None:
    service = AstraQueryService(
        orchestrator=_StubOrchestrator(result_text="Your portfolio summary is unavailable"),
        tool_executor=_StubExecutor(holdings=[]),
    )

    result = service.execute(query="hello", principal=_principal())
    assert "No holdings" in result.answer


def test_agent_run_id_is_server_generated() -> None:
    service = AstraQueryService(orchestrator=_StubOrchestrator(), tool_executor=_StubExecutor())
    first = service.execute(query="hello", principal=_principal())
    second = service.execute(query="hello", principal=_principal())

    assert first.agent_run_id != second.agent_run_id


def test_invalid_principal_rejected() -> None:
    service = AstraQueryService(orchestrator=_StubOrchestrator(), tool_executor=_StubExecutor())

    with pytest.raises(AstraServiceError) as exc:
        service.execute(query="hello", principal=SimpleNamespace(user_id=uuid4()))

    assert exc.value.code == "invalid_authenticated_principal"
