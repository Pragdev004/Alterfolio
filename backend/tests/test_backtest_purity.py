"""quant/backtest is pure: stdlib + domain + market_data only, no float, clock or randomness, no adjusted_close
(Feature 005 step 7; mirrors test_market_data_purity.py)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "app" / "quant" / "backtest"
FILES = sorted(ROOT.glob("*.py"))
CLOCK_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "random", "randint", "uniform", "choice"}


def _trees():
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in FILES]


def test_the_package_has_the_planned_modules_each_under_the_size_limit():
    assert {p.name for p in FILES} >= {
        "__init__.py", "config.py", "portfolio.py", "calendar.py", "execution.py", "engine.py", "result.py"}
    for path in FILES:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 250, path.name


def test_imports_are_stdlib_domain_and_market_data_only():
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                continue  # sibling modules of this package
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                ok = name.split(".")[0] in sys.stdlib_module_names or name == "app.domain" or name.startswith("app.domain.")
                ok = ok or name == "app.quant.market_data" or name.startswith("app.quant.market_data.")
                assert ok, f"{path.name} imports {name}"


def test_no_float_no_clock_no_randomness():
    for path, tree in _trees():
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float"), path.name
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in CLOCK_CALLS, f"{path.name}: {node.func.attr}()"
            if isinstance(node, (ast.Import, ast.ImportFrom)) and not getattr(node, "level", 0):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(m.split(".")[0] in {"random", "time", "secrets"} for m in mods), path.name


def test_the_engine_never_reads_adjusted_close():
    for path, tree in _trees():
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Attribute) and node.attr == "adjusted_close"), path.name
            assert not (isinstance(node, ast.Constant) and node.value == "adjusted_close"), path.name
