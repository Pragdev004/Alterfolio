"""quant/market_data is pure: stdlib + domain only, no float, no clock, no randomness (design invariants 1, 3)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "app" / "quant" / "market_data"
FILES = sorted(ROOT.glob("*.py"))
CLOCK_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "random", "randint", "uniform"}


def test_the_package_exists_with_the_planned_modules():
    assert {p.name for p in FILES} >= {
        "__init__.py", "bar.py", "exchange_time.py", "fingerprint.py", "provenance.py", "series.py"}


def test_imports_are_stdlib_and_domain_only():
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
            for name in names:
                ok = name.split(".")[0] in sys.stdlib_module_names or name == "app.domain" or name.startswith("app.domain.")
                # sibling modules of this package are also allowed
                ok = ok or name.startswith("app.quant.market_data")
                assert ok, f"{path.name} imports {name}"


def test_no_float_use_and_no_clock_or_randomness():
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float"), path.name
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in CLOCK_CALLS, f"{path.name}: {node.func.attr}()"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(m.split(".")[0] in {"random", "time", "secrets"} for m in mods), path.name
