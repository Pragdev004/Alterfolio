from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.dependencies.ai import get_agent_orchestrator
from app.api.router import api_router


class _NoopOrchestrator:
    def run(self, request):
        return SimpleNamespace(output_text="ok", agent_run_id=request.agent_run_id)


def _build_client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def inject_test_principal(request: Request, call_next):
        marker = request.headers.get("X-Test-Principal")
        if marker == "invalid-dict":
            request.state.authenticated_principal = {"user_id": "not-a-uuid"}
        elif marker == "malformed":
            request.state.authenticated_principal = {"bad": "shape"}
        elif marker == "invalid-raw":
            request.state.authenticated_principal = "not-a-principal"
        elif marker:
            request.state.authenticated_principal = {"user_id": marker}

        return await call_next(request)

    app.include_router(api_router)
    app.dependency_overrides[get_agent_orchestrator] = _NoopOrchestrator
    return TestClient(app)


def test_dependency_chain_missing_principal_returns_astra_401_envelope() -> None:
    client = _build_client()

    response = client.post("/astra/query", json={"query": "hello"})

    assert response.status_code == 401
    assert response.json() == {
        "code": "authentication_required",
        "message": "Authentication required",
        "agent_run_id": None,
    }


def test_dependency_chain_malformed_or_invalid_principal_returns_astra_401_envelope() -> None:
    client = _build_client()

    cases = [
        "invalid-dict",
        "malformed",
        "invalid-raw",
        "not-a-uuid",
    ]

    for marker in cases:
        response = client.post(
            "/astra/query",
            headers={"X-Test-Principal": marker},
            json={"query": "hello"},
        )
        assert response.status_code == 401
        assert response.json() == {
            "code": "invalid_authenticated_principal",
            "message": "Invalid authenticated principal",
            "agent_run_id": None,
        }


def test_dependency_chain_request_validation_returns_astra_422_envelope() -> None:
    client = _build_client()
    valid_principal = str(uuid4())

    responses = [
        client.post("/astra/query", headers={"X-Test-Principal": valid_principal}, json={}),
        client.post("/astra/query", headers={"X-Test-Principal": valid_principal}, json={"query": "   "}),
        client.post("/astra/query", headers={"X-Test-Principal": valid_principal}, json={"query": "hello", "extra": "x"}),
        client.post("/astra/query", headers={"X-Test-Principal": valid_principal}, json=["not", "object"]),
        client.post(
            "/astra/query",
            headers={"X-Test-Principal": valid_principal, "content-type": "application/json"},
            data="{\"query\":",
        ),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json() == {
            "code": "invalid_request",
            "message": "Invalid request payload",
            "agent_run_id": None,
        }


def test_identity_inputs_other_than_authenticated_principal_are_not_accepted() -> None:
    client = _build_client()

    response = client.post(
        "/astra/query?user_id=" + str(uuid4()),
        headers={"X-User-Id": str(uuid4())},
        json={"query": "hello", "user_id": str(uuid4())},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
