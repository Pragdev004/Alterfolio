"""AST import-boundary tests (design invariants 1 and 2)."""
import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
STDLIB = set(sys.stdlib_module_names)
# The only files that may import httpx (Feature 003 Yahoo adapter; Feature 009 Ollama embedding adapter).
HTTPX_FILES = frozenset({("providers", "market", "yahoo.py"), ("providers", "embedding", "ollama.py"),
                         ("analyst", "llm_openai.py")})  # Feature 010: OpenAI-compatible analyst LLM adapter
# Feature 009: the only files exempt from the float scan (embedding vectors and cosine scores). They may never reach money
# code; see `test_retrieval_float_files_cannot_reach_money_code`.
RETRIEVAL_FLOAT_FILES = frozenset({
    ("providers", "embedding", "ollama.py"), ("services", "retrieval.py"), ("repositories", "chunks.py"),
})


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
            # Feature 005 (D9): quant/backtest may import the market-data value types; nothing else inside quant.
            ok = ok or (path.parent.name in ("backtest", "bias_cost", "luck_test") and (name == "app.quant.market_data" or name.startswith("app.quant.market_data.")))
            # Feature 008: quant/regime_split consumes the Feature 006 and 007 packages and the market-data value types.
            ok = ok or (path.parent.name == "regime_split" and (name in ("app.quant.market_data", "app.quant.bias_cost", "app.quant.luck_test") or name.startswith(("app.quant.market_data.", "app.quant.bias_cost.", "app.quant.luck_test."))))
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
            if path.relative_to(APP).parts in RETRIEVAL_FLOAT_FILES:
                continue  # Feature 009 exemption, compensated by the money-reachability test below
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
                assert rel in HTTPX_FILES, f"{path.name} imports {name}"
            if rel[0] == "providers":
                continue
            if name.startswith("app.providers.market.yahoo"):
                assert rel == ("api", "main.py"), f"{path.name} imports the concrete provider"
            if name.startswith("app.providers"):
                assert rel[0] in ("services", "api"), f"{path.name} imports {name}"
                if rel[0] == "services":
                    # the provider-neutral ports (quotes: 003, daily bars: 004, embeddings: 009); never an adapter
                    assert name in ("app.providers.market.port", "app.providers.market.history_port",
                                    "app.providers.embedding.port"), (
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


# ---- Feature 009 (spec section 5): retrieval boundary; additions only, nothing above is relaxed ---------------------------
#
# Guaranteed: in the STATIC, EXPLICIT import graph of app/ (absolute and relative imports, `from package import module`
# included), the retrieval modules are imported only by approved retrieval modules, the Ollama adapter by nothing, no money
# module imports retrieval code, and the three float-exempt files cannot transitively import any money module.
# Not guaranteed: runtime data flow. These tests do not see values a caller passes in, dynamic imports or dispatch, package
# `__init__` side effects (the embedding package's init is checked on its own), or values that cross through the database,
# JSON or a later API layer. A future caller that holds retrieval floats and money Decimals together (an API route,
# Feature 010) is outside these tests and needs its own review.

RETRIEVAL_IMPORTERS = {
    "app.services.retrieval": frozenset(),  # no composition root or API in Feature 009
    "app.repositories.chunks": frozenset({"app.services.retrieval"}),
    "app.models.chunk": frozenset({"app.repositories.chunks"}),
    "app.providers.embedding.port": frozenset({"app.providers.embedding.ollama", "app.services.retrieval"}),
    "app.providers.embedding.ollama": frozenset(),  # imported only by tests in Feature 009
    "app.domain.retrieval": frozenset({
        "app.services.retrieval", "app.repositories.chunks", "app.models.chunk", "app.providers.embedding.port",
        "app.providers.embedding.ollama",
        "app.analyst.graph",  # Feature 010: re-checks the cutoff with domain `to_utc`/`validate_text`/`Unavailable`
    }),
}
MONEY_PREFIXES = ("app.quant", "app.schemas", "app.api", "app.providers.market")
MONEY_MODULES = frozenset({"app.models.trade", "app.models.import_batch", "app.domain.numeric"})


def _module(path: Path) -> str:
    dotted = _dotted(path)
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def _resolved(source: str, module: str, is_package: bool) -> set[str]:
    """Every module name an import may bind: absolute and relative imports, and `from pkg import name` as both `pkg` and
    `pkg.name` (the latter may be a submodule). Unlike `_imports`, nothing is skipped."""
    package = module if is_package else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)] + ([node.module] if node.module else []))
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return found


def _raw_imports() -> dict[str, set[str]]:
    return {
        _module(path): _resolved(path.read_text(encoding="utf-8"), _module(path), path.name == "__init__.py")
        for path in sorted(APP.rglob("*.py"))
    }


def _graph() -> dict[str, set[str]]:
    raw = _raw_imports()
    return {module: {n for n in names if n in raw and n != module} for module, names in raw.items()}


def _closure(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        for nxt in graph.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _is_money(name: str) -> bool:
    """Conservative: every service and repository except the retrieval ones counts as money code."""
    if name in MONEY_MODULES or any(name == p or name.startswith(p + ".") for p in MONEY_PREFIXES):
        return True
    if name.startswith("app.services.") and name != "app.services.retrieval":
        return True
    return name.startswith("app.repositories.") and name != "app.repositories.chunks"


def test_resolved_import_helper_sees_from_and_relative_imports():
    """The guards below are only as good as this helper, so it is checked on fixtures and on today's code."""
    src = "from app.providers.embedding import ollama\nfrom . import chunks\nfrom .port import X\nimport app.domain.numeric\n"
    assert {"app.providers.embedding.ollama", "app.services.chunks", "app.services.port", "app.domain.numeric"} <= _resolved(
        src, "app.services.retrieval", False)
    assert "app.providers.embedding.port" in _resolved("from .port import Batch", "app.providers.embedding", True)
    assert _closure({"a": {"b"}, "b": {"c"}, "c": {"a"}}, "a") == {"a", "b", "c"}
    graph = _graph()
    assert "app.models.import_batch" in graph["app.models.trade"]  # `from app.models import import_batch` is seen
    assert "app.domain.numeric" in _closure(graph, "app.services.ledger")
    for money in ("app.services.ledger", "app.services.holdings", "app.repositories.trade_repository", "app.models.trade",
                  "app.domain.numeric", "app.quant.backtest", "app.providers.market.port", "app.api.main"):
        assert _is_money(money), money
    for neutral in ("app.services.retrieval", "app.repositories.chunks", "app.domain.retrieval", "app.db.column_types",
                    "app.models.user", "app.models.base", "app.providers.embedding.port", "app.services"):
        assert not _is_money(neutral), neutral


def test_embedding_package_init_stays_empty():
    """Importing the port runs `providers/embedding/__init__.py`; it must never pull in the adapter (and httpx)."""
    path = APP / "providers" / "embedding" / "__init__.py"
    if not path.exists():
        return  # Feature 009 code is not written yet
    body = ast.parse(path.read_text(encoding="utf-8")).body
    assert all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
               for n in body) and len(body) <= 1, "providers/embedding/__init__.py must stay empty (a docstring at most)"


def test_nothing_in_app_imports_the_ollama_adapter():
    """Feature 009 has no composition root: services, repositories, api and every other app module never see the adapter."""
    for module, names in _raw_imports().items():
        bad = sorted(n for n in names if n == "app.providers.embedding.ollama" or n.startswith("app.providers.embedding.ollama."))
        assert not bad, f"{module} imports {bad}"


def test_retrieval_modules_are_imported_only_inside_the_retrieval_boundary():
    """Retrieval code is not an application dependency: each retrieval module has a fixed importer allowlist (none of them a
    money module), checked on resolved imports so even a module that does not exist yet cannot be imported elsewhere."""
    raw = _raw_imports()
    for target, allowed in RETRIEVAL_IMPORTERS.items():
        importers = {m for m, names in raw.items() if target in names}
        assert importers <= allowed, f"{target} is imported by {sorted(importers - allowed)}"
        assert not any(_is_money(m) for m in allowed), target


def test_retrieval_float_files_cannot_reach_money_code():
    """The float-exempt files may not transitively import any money module, and never import `decimal`."""
    graph = _graph()
    for rel in sorted(RETRIEVAL_FLOAT_FILES):
        path = APP.joinpath(*rel)
        if not path.exists():
            continue  # Feature 009 code is not written yet
        module = _module(path)
        money = sorted(n for n in _closure(graph, module) if _is_money(n))
        assert not money, f"{module} reaches money code: {money}"
        names = _resolved(path.read_text(encoding="utf-8"), module, False)
        assert "decimal" not in {_top(n) for n in names}, f"{module} imports decimal"
