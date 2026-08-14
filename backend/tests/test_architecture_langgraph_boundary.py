from __future__ import annotations

import ast
from pathlib import Path

DISALLOWED_PREFIXES = (
    "langgraph",
    "langchain",
    "langchain_openai",
)


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _import_targets(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    return imports


def test_domain_and_application_layers_do_not_import_langgraph_or_langchain() -> None:
    project_root = Path(__file__).resolve().parents[1]

    guarded_roots = [
        project_root / "app" / "models",
        project_root / "app" / "services",
    ]

    violations: list[str] = []

    for root in guarded_roots:
        for path in _iter_python_files(root):
            for target in _import_targets(path):
                if target.startswith(DISALLOWED_PREFIXES):
                    violations.append(f"{path}: {target}")

    assert violations == []
