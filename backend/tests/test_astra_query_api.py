from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.dependencies.astra import get_astra_query_service
from app.api.router import api_router
from app.services.ai.astra_query_service import AstraServiceError
from app.services.authenticated_principal import AuthenticatedPrincipal


def _build_app(service_stub) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def inject_test_principal(request: Request, call_next):
        principal_header = request.headers.get("X-Test-Principal")
        if principal_header == "invalid":
            request.state.authenticated_principal = {"user_id": "not-a-uuid"}
        elif principal_header:
            request.state.authenticated_principal = AuthenticatedPrincipal(
                user_id=UUID(principal_header)
            )
        response = await call_next(request)
        return response

    app.include_router(api_router)
    app.dependency_overrides[get_astra_query_service] = lambda: service_stub
    return TestClient(app)


class _SuccessService:
    def execute(self, *, query: str, principal: AuthenticatedPrincipal, tool_executor=None):
        return SimpleNamespace(answer=f"ok:{query}", agent_run_id=uuid4())


def test_post_astra_query_success() -> None:
    client = _build_app(_SuccessService())
    user = str(uuid4())

    response = client.post(
        "/astra/query",
        headers={"X-Test-Principal": user},
        json={"query": "   summarize portfolio   "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "ok:summarize portfolio"
    UUID(body["agent_run_id"])


def test_astra_query_validation_failures() -> None:
    client = _build_app(_SuccessService())
    user = str(uuid4())

    responses = [
        client.post("/astra/query", headers={"X-Test-Principal": user}, json={}),
        client.post("/astra/query", headers={"X-Test-Principal": user}, json={"query": "   "}),
        client.post("/astra/query", headers={"X-Test-Principal": user}, json={"query": "bad\u0000query"}),
        client.post(
            "/astra/query",
            headers={"X-Test-Principal": user},
            json={"query": "x", "extra": "nope"},
        ),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json() == {
            "code": "invalid_request",
            "message": "Invalid request payload",
            "agent_run_id": None,
        }


def test_client_identity_fields_rejected() -> None:
    client = _build_app(_SuccessService())
    user = str(uuid4())

    payloads = [
        {"query": "x", "user_id": str(uuid4())},
        {"query": "x", "portfolio_id": str(uuid4())},
    ]

    for payload in payloads:
        response = client.post("/astra/query", headers={"X-Test-Principal": user}, json=payload)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"


def test_missing_or_invalid_principal_rejected() -> None:
    client = _build_app(_SuccessService())

    missing = client.post("/astra/query", json={"query": "hello"})
    assert missing.status_code == 401
    assert missing.json() == {
        "code": "authentication_required",
        "message": "Authentication required",
        "agent_run_id": None,
    }

    x_user_only = client.post(
        "/astra/query",
        headers={"X-User-Id": str(uuid4())},
        json={"query": "hello"},
    )
    assert x_user_only.status_code == 401
    assert x_user_only.json()["code"] == "authentication_required"

    invalid = client.post(
        "/astra/query",
        headers={"X-Test-Principal": "invalid"},
        json={"query": "hello"},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {
        "code": "invalid_authenticated_principal",
        "message": "Invalid authenticated principal",
        "agent_run_id": None,
    }


def test_astra_error_mapping_contract() -> None:
    run_id = uuid4()

    class _ErrorService:
        def execute(self, *, query: str, principal: AuthenticatedPrincipal, tool_executor=None):
            raise AstraServiceError(
                code="model_provider_failed",
                message="Model provider failed",
                status_code=502,
                agent_run_id=run_id,
            )

    client = _build_app(_ErrorService())

    response = client.post(
        "/astra/query",
        headers={"X-Test-Principal": str(uuid4())},
        json={"query": "hello"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "code": "model_provider_failed",
        "message": "Model provider failed",
        "agent_run_id": str(run_id),
    }
