"""Feature 011: analyst wiring, endpoint isolation, import boundaries (spec A6-A8, A11)."""

import ast
import socket
from datetime import date
from pathlib import Path

import pytest
from analysis_helpers import D_ASOF, NOW, TRADED, FakeBars, config, seed_round_trips
from conftest import USER_A, USER_B
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.analyst.llm import TemplateLLM
from app.analyst.service import ask
from app.api.analyst_wiring import quant_tools_from
from app.api.deps import get_current_user_id
from app.api.main import create_app
from app.config import Settings
from app.repositories.trade_repository import TradeRepository
from app.services.portfolio_analysis import PortfolioAnalysisService

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original = socket.socket.connect

    def guarded(self, address, *a, **k):  # loopback is allowed: the test client's event loop uses a socketpair
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
            raise AssertionError(f"network access in a test: {address!r}")
        return original(self, address, *a, **k)
    monkeypatch.setattr(socket.socket, "connect", guarded)


def service(session, provider=None):
    return PortfolioAnalysisService(repo=TradeRepository(session), provider=provider or FakeBars(), clock=lambda: NOW, config=config())


def test_a6_end_to_end_real_wiring_is_verified_and_cites_facts(session):
    seed_round_trips(session, USER_A, 14)
    svc = service(session)
    facts = {f.source for f in svc.analyse(USER_A, D_ASOF).facts}  # citations name the fact source
    for question in ("Was my last buy skill or luck?", "What did my behaviour cost me?", "How did I do in each regime?"):
        answer = ask(USER_A, question, D_ASOF, llm=TemplateLLM(), tools=quant_tools_from(svc.analyse), retriever=None)
        assert answer.verified is True and answer.attempts == 1
        tool_refs = [c.ref for c in answer.citations if c.kind == "tool"]
        assert tool_refs and set(tool_refs) <= facts


def test_a6_unavailable_facts_pass_through_as_unavailable(session):
    svc = service(session)  # no trades at all
    answer = ask(USER_A, "What did my behaviour cost me?", D_ASOF, llm=TemplateLLM(), tools=quant_tools_from(svc.analyse))
    assert answer.verified is True and "Unavailable" in answer.text


def _app(engine, user, provider):
    return create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=user),
                      clock=lambda: NOW, history_provider=provider, analysis_config=config())


def test_a7_endpoint_is_user_isolated(engine, session):
    seed_round_trips(session, USER_A, 14)
    provider = FakeBars()
    app = _app(engine, USER_A, provider)
    client = TestClient(app)
    body = {"question": "How did I do in each regime?", "as_of": D_ASOF.isoformat()}
    a = client.post("/api/analyst/ask", json=body)
    assert a.status_code == 200 and a.json()["verified"] is True
    traded_calls = sum(1 for inst, *_ in provider.calls if inst == TRADED)
    assert traded_calls > 0
    app.dependency_overrides[get_current_user_id] = lambda: USER_B  # same app instance, other user
    b = client.post("/api/analyst/ask", json=body)
    assert b.status_code == 200 and b.json()["text"] != a.json()["text"]
    assert sum(1 for inst, *_ in provider.calls if inst == TRADED) == traded_calls  # B's request never fetched A's listing


def test_a7_request_cannot_carry_a_user_id_and_future_dates_are_rejected(engine, session):
    client = TestClient(_app(engine, USER_A, FakeBars()))
    ok = {"question": "q?", "as_of": D_ASOF.isoformat()}
    assert client.post("/api/analyst/ask", json={**ok, "user_id": str(USER_B)}).status_code == 422
    assert client.post("/api/analyst/ask", json={**ok, "as_of": "2026-12-01"}).status_code == 422
    assert client.post("/api/analyst/ask", json={"question": "  ", "as_of": D_ASOF.isoformat()}).status_code == 422


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_a8_import_boundaries():
    svc = _imports(APP / "services" / "portfolio_analysis.py")
    assert not [m for m in svc if m.startswith(("app.analyst", "app.api", "httpx", "langgraph", "langchain"))]
    assert not [m for m in svc if m.startswith("app.providers") and m != "app.providers.market.history_port"]
    for path in (APP / "analyst").glob("*.py"):
        assert not [m for m in _imports(path) if m.startswith(("app.quant", "app.services", "app.repositories", "app.models"))], path
    for layer in ("domain", "quant", "models", "repositories", "services"):
        for path in (APP / layer).rglob("*.py"):
            assert not [m for m in _imports(path) if m.startswith("app.analyst")], path


def test_a10_demo_runs_offline_and_every_answer_is_verified(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, "scripts/demo_analyst.py", str(tmp_path)], cwd=root, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-500:]
    assert "4/4 answers verified" in run.stdout
    assert list(tmp_path.glob("demo-analyst-*.md"))  # written to tmp_path, never into docs/reports
