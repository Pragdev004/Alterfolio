from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import portfolio as portfolio_routes
from app.schemas.ai import PortfolioAnalysis, PortfolioAnalysisResponse
from app.services.ai.agent_orchestrator import AgentOrchestrationResult
from app.services.ai.astra_query_service import AstraQueryService
from app.services.authenticated_principal import AuthenticatedPrincipal


class _Orchestrator:
    def run(self, request):
        return AgentOrchestrationResult(
            output_text="final safe answer",
            agent_run_id=request.agent_run_id,
        )


class _Executor:
    portfolio_summary = SimpleNamespace(holdings=[])


def test_logs_do_not_include_query_answer_or_holdings(caplog) -> None:
    service = AstraQueryService(orchestrator=_Orchestrator(), tool_executor=_Executor())
    principal = AuthenticatedPrincipal(user_id=uuid4())

    secret_query = "buy 10 TCS and here is my secret balance"

    with caplog.at_level(logging.INFO):
        try:
            service.execute(query=secret_query, principal=principal)
        except Exception:
            # transaction guard might trigger depending on query text.
            pass

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret balance" not in logs
    assert "buy 10 TCS" not in logs
    assert "final safe answer" not in logs


def test_structured_portfolio_analysis_route_remains_available() -> None:
    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")

    response_payload = PortfolioAnalysisResponse(
        analysis=PortfolioAnalysis(
            overview="o",
            diversification_analysis="d",
            risk_assessment="r",
            strengths=["s"],
            weaknesses=["w"],
            recommendations=["rec"],
        ),
        model="test-model",
        generated_at=datetime.utcnow(),
    )

    class _Workflow:
        def analyze_portfolio(self):
            return response_payload

    app.dependency_overrides[portfolio_routes.get_ai_workflow_service] = lambda: _Workflow()

    response = TestClient(app).get("/portfolio/analysis")
    assert response.status_code == 200
    assert response.json()["analysis"]["overview"] == "o"
