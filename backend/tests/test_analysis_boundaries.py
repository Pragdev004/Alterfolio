"""Feature 013a import boundaries (spec T10). The analysis read path never touches the analyst, httpx or quant types."""

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
STDLIB = set(sys.stdlib_module_names)


def imports(rel: str) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse((APP / rel).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


def test_t10_api_analysis_layer_imports_no_analyst_httpx_or_quant():
    for rel in ("api/routes/analysis.py", "api/analysis_presenter.py"):
        bad = [m for m in imports(rel) if m.startswith(("app.analyst", "app.quant", "httpx", "langgraph", "langchain", "app.providers"))]
        assert not bad, (rel, bad)


def test_t10_read_services_import_no_analyst_api_or_httpx():
    for rel in ("services/analysis_view.py", "services/analysis_read.py"):
        bad = [m for m in imports(rel) if m.startswith(("app.analyst", "app.api", "httpx", "langgraph", "langchain"))]
        assert not bad, (rel, bad)


def test_t10_domain_display_is_stdlib_and_domain_only():
    bad = [m for m in imports("domain/display.py") if m.split(".")[0] not in STDLIB and not m.startswith("app.domain")]
    assert not bad, bad


def test_t10_schemas_display_imports_only_pydantic_stdlib_and_domain():
    bad = [m for m in imports("schemas/display.py")
           if m.split(".")[0] not in STDLIB and not m.startswith(("app.domain", "pydantic"))]
    assert not bad, bad

