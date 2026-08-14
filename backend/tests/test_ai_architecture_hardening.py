from __future__ import annotations

import ast
from pathlib import Path
import inspect
from types import SimpleNamespace

import pytest
from fastapi.params import Depends

from app.api.dependencies import ai as ai_dependencies
from app.api.routes import portfolio as portfolio_routes
from app.schemas.ai import PortfolioAnalysis
from app.services.ai.ai_service import AIService, AIServiceConfigurationError


def test_ai_service_has_no_infrastructure_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "ai" / "ai_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert all(not target.startswith("app.infrastructure") for target in imports)


def test_ai_service_constructs_without_astra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.ai.ai_service.get_settings", lambda: SimpleNamespace(azure_openai_deployment="dep"))
    monkeypatch.setattr(
        "app.services.ai.ai_service.get_ai_client",
        lambda: SimpleNamespace(responses=SimpleNamespace(parse=lambda **_: None, create=lambda **_: None)),
    )

    service = AIService(agent_orchestrator=None)

    assert service is not None


def test_run_agent_without_orchestrator_fails_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.ai.ai_service.get_settings", lambda: SimpleNamespace(azure_openai_deployment="dep"))
    monkeypatch.setattr(
        "app.services.ai.ai_service.get_ai_client",
        lambda: SimpleNamespace(responses=SimpleNamespace(parse=lambda **_: None, create=lambda **_: None)),
    )

    service = AIService(agent_orchestrator=None)

    with pytest.raises(AIServiceConfigurationError, match="Agent orchestrator is not configured"):
        service.run_agent(user_input="hello", executor=SimpleNamespace(execute=lambda *_: {}))


def test_structured_analysis_works_without_astra_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_analysis = PortfolioAnalysis(
        overview="o",
        diversification_analysis="d",
        risk_assessment="r",
        strengths=["s"],
        weaknesses=["w"],
        recommendations=["rec"],
    )

    fake_client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(output_parsed=parsed_analysis),
            create=lambda **_: None,
        )
    )

    monkeypatch.setattr("app.services.ai.ai_service.get_settings", lambda: SimpleNamespace(azure_openai_deployment="dep"))
    monkeypatch.setattr("app.services.ai.ai_service.get_ai_client", lambda: fake_client)

    monkeypatch.setattr(
        "app.services.ai.ai_service.build_portfolio_analysis_prompt",
        lambda *_: "prompt",
    )

    service = AIService(agent_orchestrator=None)
    result = service.analyze_portfolio(
        SimpleNamespace(portfolio=SimpleNamespace(holdings=[]), quotes=[], news=[])
    )

    assert result.analysis == parsed_analysis
    assert result.model == "dep"


def test_structured_dependency_does_not_initialize_astra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.ai.ai_service.get_settings", lambda: SimpleNamespace(azure_openai_deployment="dep"))
    monkeypatch.setattr(
        "app.services.ai.ai_service.get_ai_client",
        lambda: SimpleNamespace(responses=SimpleNamespace(parse=lambda **_: None, create=lambda **_: None)),
    )

    called = {"azure": 0, "orchestrator": 0}

    class _BoomAzure:
        def __init__(self, *args, **kwargs):
            called["azure"] += 1
            raise AssertionError("should not be called")

    class _BoomOrchestrator:
        def __init__(self, *args, **kwargs):
            called["orchestrator"] += 1
            raise AssertionError("should not be called")

    monkeypatch.setattr(ai_dependencies, "AzureFoundryReasoningEngine", _BoomAzure)
    monkeypatch.setattr(ai_dependencies, "LangGraphAgentOrchestrator", _BoomOrchestrator)

    service = ai_dependencies.get_structured_ai_service()

    assert isinstance(service, AIService)
    assert called == {"azure": 0, "orchestrator": 0}


def test_agent_dependency_composes_azure_and_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class _SpyAzure:
        def __init__(self, *, client, model, max_output_tokens):
            calls.append(("azure", (client, model, max_output_tokens)))

    class _SpyOrchestrator:
        def __init__(
            self,
            *,
            reasoning_engine,
            max_iterations,
            max_tool_calls,
            require_portfolio_grounding,
        ):
            calls.append(
                (
                    "orchestrator",
                    (reasoning_engine, max_iterations, max_tool_calls, require_portfolio_grounding),
                )
            )

    fake_client = object()
    monkeypatch.setattr(ai_dependencies, "get_ai_client", lambda: fake_client)
    monkeypatch.setattr(ai_dependencies, "AzureFoundryReasoningEngine", _SpyAzure)
    monkeypatch.setattr(ai_dependencies, "LangGraphAgentOrchestrator", _SpyOrchestrator)

    orchestrator = ai_dependencies.get_agent_orchestrator(
        settings=SimpleNamespace(
            azure_openai_deployment="dep",
            astra_provider_max_output_tokens=123,
            astra_max_reasoning_iterations=4,
            astra_max_cumulative_tool_calls=9,
        )
    )

    assert orchestrator is not None
    assert calls[0][0] == "azure"
    assert calls[1][0] == "orchestrator"


def test_orchestrator_boundary_does_not_use_provider_specific_methods() -> None:
    path = Path(__file__).resolve().parents[1] / "app" / "infrastructure" / "astra" / "langgraph_agent_orchestrator.py"
    content = path.read_text(encoding="utf-8")

    forbidden = [
        "extract_tool_calls",
        "parse_arguments",
        "serialize_result",
        "build_function_call_output",
    ]
    assert all(name not in content for name in forbidden)


def test_portfolio_route_uses_structured_ai_dependency() -> None:
    signature = inspect.signature(portfolio_routes.get_ai_workflow_service)
    ai_param = signature.parameters["ai_service"]

    assert isinstance(ai_param.default, Depends)
    assert ai_param.default.dependency is ai_dependencies.get_structured_ai_service
