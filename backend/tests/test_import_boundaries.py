"""AST import-boundary tests (design invariants 1 and 2)."""
import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
STDLIB = set(sys.stdlib_module_names)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            found.add(node.module or "")
    return found


def _files(package: str) -> list[Path]:
    root = APP / package
    return sorted(root.rglob("*.py")) if root.exists() else []


def _top(name: str) -> str:
    return name.split(".")[0]


def test_domain_imports_only_the_standard_library():
    files = _files("domain")
    assert files, "domain package must exist"
    for path in files:
        for name in _imports(path):
            ok = _top(name) in STDLIB or name == "app.domain" or name.startswith("app.domain.")
            assert ok, f"{path.name} imports non-stdlib {name}"


def test_quant_imports_only_stdlib_and_domain():
    for path in _files("quant"):
        for name in _imports(path):
            ok = _top(name) in STDLIB or name == "app.domain" or name.startswith("app.domain.")
            assert ok, f"{path.name} imports {name}"


def test_nothing_outside_ai_imports_ai():
    for path in sorted(APP.rglob("*.py")):
        if "ai" in path.relative_to(APP).parts[:1]:
            continue
        for name in _imports(path):
            assert name != "app.ai" and not name.startswith("app.ai."), f"{path} imports {name}"


def test_holdings_service_is_pure():
    path = APP / "services" / "holdings.py"
    assert path.exists(), "services/holdings.py must exist"
    banned = {"sqlalchemy", "fastapi", "pydantic", "app.models", "app.repositories", "app.schemas", "app.api"}
    for name in _imports(path):
        assert not any(name == b or name.startswith(b + ".") for b in banned), f"holdings imports {name}"


def test_services_do_not_import_schemas_or_api():
    for path in _files("services"):
        for name in _imports(path):
            assert not name.startswith(("app.schemas", "app.api")), f"{path.name} imports {name}"


def test_layer_direction_is_respected():
    forbidden = {
        "repositories": ("app.services", "app.api", "app.schemas"),
        "models": ("app.services", "app.repositories", "app.api", "app.schemas"),
        "schemas": ("app.services", "app.repositories", "app.models", "app.api"),
    }
    for package, banned in forbidden.items():
        for path in _files(package):
            for name in _imports(path):
                assert not name.startswith(banned), f"{package}/{path.name} imports {name}"


def test_money_paths_do_not_use_float():
    for package in ("domain", "services", "repositories", "models", "schemas"):
        for path in _files(package):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                    raise AssertionError(f"{path.name}: float() call")
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    raise AssertionError(f"{path.name}: float literal {node.value}")
