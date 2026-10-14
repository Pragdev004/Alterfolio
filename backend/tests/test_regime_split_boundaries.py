"""Feature 008 boundary scans: imports, numeric policy, no clock or randomness, Features 006/007 independent of 008."""

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
PKG = APP / "quant" / "regime_split"
STDLIB = set(sys.stdlib_module_names)
ALLOWED_QUANT = ("app.quant.market_data", "app.quant.bias_cost", "app.quant.luck_test")


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _files() -> list[Path]:
    files = sorted(PKG.glob("*.py"))
    assert files
    return files


def test_imports_are_stdlib_domain_and_the_three_consumed_quant_packages_only():
    for path in _files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.level == 1, path.name  # relative imports stay inside the package
                continue
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                ok = (name.split(".")[0] in STDLIB or name == "app.domain" or name.startswith("app.domain.")
                      or any(name == q or name.startswith(q + ".") for q in ALLOWED_QUANT))
                assert ok, f"{path.name} imports {name}"


def test_no_float_literal_or_float_call_money_is_decimal():
    for path in _files():
        for node in ast.walk(_tree(path)):
            assert not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float"), path.name
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name


def test_no_clock_randomness_or_dynamic_import():
    banned_modules = {"random", "secrets", "time", "importlib"}
    for path in _files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not banned_modules & {m.split(".")[0] for m in mods}, path.name
            if isinstance(node, ast.Attribute) and node.attr in {"now", "today", "utcnow", "time", "monotonic"}:
                raise AssertionError(f"{path.name} reads a clock via .{node.attr}")


def test_features_006_and_007_never_import_008():
    for package in ("bias_cost", "luck_test"):
        for path in sorted((APP / "quant" / package).glob("*.py")):
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.ImportFrom):
                    assert "regime_split" not in (node.module or ""), path.name


def test_no_new_dependency_is_declared():
    text = (APP.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "statsmodels" not in text
