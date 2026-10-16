"""Feature 010 import boundaries (A9)."""
from pathlib import Path

from tests.test_import_boundaries import APP, _files, _imports, _top

LIBS = {"langgraph", "langchain_core", "langchain"}
LOWER = ("domain", "quant", "models", "repositories", "db", "providers", "schemas")


def _is_analyst(name: str) -> bool:
    return name == "app.analyst" or name.startswith("app.analyst.")


def test_analyst_package_exists():
    assert _files("analyst"), "app/analyst must exist"


def test_lower_layers_never_import_analyst_or_langgraph():
    for package in LOWER:
        for path in _files(package):
            for name in _imports(path):
                assert not _is_analyst(name) and _top(name) not in LIBS, f"{package}/{path.name} imports {name}"


def test_services_never_import_analyst():
    for path in _files("services"):
        for name in _imports(path):
            assert not _is_analyst(name) and _top(name) not in LIBS, f"services/{path.name} imports {name}"


def test_only_graph_py_imports_langgraph_or_langchain():
    for path in _files("analyst"):
        for name in _imports(path):
            if _top(name) in LIBS:
                assert path.name == "graph.py", f"{path.name} imports {name}"


def test_only_llm_openai_imports_httpx():
    for path in _files("analyst"):
        for name in _imports(path):
            if _top(name) == "httpx":
                assert path.name == "llm_openai.py", f"{path.name} imports {name}"


def test_analyst_imports_domain_only_from_app_and_never_quant_adapters_or_orm():
    for path in _files("analyst"):
        for name in _imports(path):
            if name == "app" or name.startswith("app."):
                ok = name == "app.domain" or name.startswith("app.domain.") or _is_analyst(name)
                assert ok, f"analyst/{path.name} imports {name}"
            assert _top(name) not in {"sqlalchemy", "fastapi", "pydantic", "starlette"}, f"analyst/{path.name} imports {name}"


def test_analyst_has_no_float_use():
    import ast
    for path in _files("analyst"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Name) and node.id == "float"), f"analyst/{path.name} uses float"
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"analyst/{path.name} float literal"


def test_pins_are_exact():
    root = Path(__file__).resolve().parent.parent
    text = (root / "constraints.txt").read_text(encoding="utf-8").lower()
    for lib in ("langgraph==", "langchain-core=="):
        assert lib in text, f"{lib} must be pinned exactly in constraints.txt"
