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
        "providers": ("app.services", "app.repositories", "app.models", "app.schemas", "app.api", "app.db"),
    }
    for package, banned in forbidden.items():
        for path in _files(package):
            for name in _imports(path):
                assert not name.startswith(banned), f"{package}/{path.name} imports {name}"


def test_money_paths_do_not_use_float():
    for package in ("domain", "services", "repositories", "models", "schemas", "providers"):
        for path in _files(package):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                    raise AssertionError(f"{path.name}: float() call")
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    raise AssertionError(f"{path.name}: float literal {node.value}")


def test_tradebook_parser_is_pure():
    path = APP / "services" / "tradebook_parser.py"
    assert path.exists(), "services/tradebook_parser.py must exist"
    banned = {
        "sqlalchemy", "fastapi", "starlette", "pydantic", "uuid", "time", "app.models", "app.repositories",
        "app.schemas", "app.api", "app.db",
    }
    for name in _imports(path):
        assert not any(name == b or name.startswith(b + ".") for b in banned), f"tradebook_parser imports {name}"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "open", "read_text", "read_bytes"}, node.attr
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "print"}, node.id


def test_tradebook_import_service_stays_in_the_service_layer():
    path = APP / "services" / "tradebook_import.py"
    assert path.exists(), "services/tradebook_import.py must exist"
    banned = ("fastapi", "starlette", "pydantic", "app.api", "app.schemas")
    for name in _imports(path):
        assert not name.startswith(banned), f"tradebook_import imports {name}"


def test_provider_code_is_isolated_behind_the_market_port():
    """Feature 003: only providers/ knows httpx/Yahoo; services see the port; lower layers never see providers."""
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).parts
        for name in _imports(path):
            if _top(name) == "httpx":
                assert rel == ("providers", "market", "yahoo.py"), f"{path.name} imports {name}"
            if rel[0] == "providers":
                continue
            if name.startswith("app.providers.market.yahoo"):
                assert rel == ("api", "main.py"), f"{path.name} imports the concrete provider"
            if name.startswith("app.providers"):
                assert rel[0] in ("services", "api"), f"{path.name} imports {name}"
                if rel[0] == "services":
                    # the two provider-neutral ports (quotes: Feature 003, daily bars: Feature 004); never an adapter
                    assert name in ("app.providers.market.port", "app.providers.market.history_port"), (
                        f"{path.name} imports {name}")
    for path in _files("providers"):
        for name in _imports(path):
            assert _top(name) in STDLIB | {"httpx", "app"}, f"{path.name} imports {name}"


def test_portfolio_summary_logic_is_framework_free():
    path = APP / "services" / "portfolio_summary.py"
    assert path.exists()
    for name in _imports(path):
        assert _top(name) not in {"sqlalchemy", "fastapi", "pydantic", "httpx"}, f"portfolio_summary imports {name}"
        assert not name.startswith(("app.models", "app.repositories", "app.schemas", "app.api")), name


# ---- Feature 004 (plan section 11, "Boundary tests"): additions only; nothing above is relaxed ------------------------


def _dotted(path: Path) -> str:
    return ".".join(path.relative_to(APP.parent).with_suffix("").parts)


def test_providers_import_only_domain_and_other_provider_modules():
    """providers -> quant (or anything above providers) is forbidden; the older test only checked a coarse prefix."""
    for path in _files("providers"):
        for name in _imports(path):
            if _top(name) == "app":
                assert name == "app.domain" or name.startswith(("app.domain.", "app.providers.")), (
                    f"providers/{path.name} imports {name}")


def test_quant_never_imports_providers_services_httpx_or_any_upper_layer():
    banned = ("app.providers", "app.services", "app.api", "app.schemas", "app.models", "app.repositories", "app.db", "app.ai")
    for path in _files("quant"):
        for name in _imports(path):
            assert not name.startswith(banned), f"quant/{path.name} imports {name}"
            assert _top(name) not in {"httpx", "sqlalchemy", "fastapi", "pydantic", "starlette"}, f"{path.name} imports {name}"


def test_domain_never_imports_any_other_layer():
    for path in _files("domain"):
        for name in _imports(path):
            assert not name.startswith("app.") or name == "app.domain" or name.startswith("app.domain."), (
                f"domain/{path.name} imports {name}")


def test_only_the_adapter_and_the_series_service_import_the_daily_bar_port():
    importers = {
        _dotted(path)
        for path in sorted(APP.rglob("*.py"))
        if any(name == "app.providers.market.history_port" for name in _imports(path))
    }
    assert importers == {"app.providers.market.yahoo", "app.services.market_series"}


def test_services_and_api_never_import_the_concrete_daily_bar_adapter():
    for path in _files("services") + _files("api") + _files("quant"):
        for name in _imports(path):
            if name.startswith("app.providers.market.yahoo"):
                assert path == APP / "api" / "main.py", f"{path.name} imports {name}"  # composition root only


def test_the_market_series_service_is_framework_free_and_reaches_providers_only_via_ports():
    path = APP / "services" / "market_series.py"
    assert path.exists()
    banned = ("sqlalchemy", "fastapi", "starlette", "pydantic", "httpx", "app.api", "app.schemas", "app.models",
              "app.repositories", "app.db", "app.ai", "app.providers.market.yahoo")
    names = _imports(path)
    for name in names:
        assert not any(name == b or name.startswith(b + ".") for b in banned), f"market_series imports {name}"
    assert {n for n in names if n.startswith("app.providers")} == {"app.providers.market.history_port"}
    assert any(n.startswith("app.quant.market_data") for n in names)  # services -> quant is the permitted direction


def test_no_relative_import_can_reach_outside_its_own_package_or_hide_a_layer_crossing():
    """The AST scans above ignore relative imports, so any relative import in a guarded layer must stay inside it."""
    for package in ("domain", "quant", "providers"):
        for path in _files(package):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level:
                    assert node.level == 1, f"{package}/{path.name} uses a parent-relative import"
                if isinstance(node, ast.Name):
                    assert node.id != "__import__", f"{package}/{path.name} uses __import__"
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    assert "importlib" not in [m.split(".")[0] for m in mods], f"{package}/{path.name} uses importlib"


def test_daily_bar_numeric_paths_use_no_float():
    """Feature 004 numeric policy (F1): no float() and no float literal in the port, the adapter or quant/market_data."""
    files = [APP / "providers" / "market" / "history_port.py", APP / "providers" / "market" / "yahoo.py",
             APP / "services" / "market_series.py", *sorted((APP / "quant" / "market_data").glob("*.py"))]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float"), path.name
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name
