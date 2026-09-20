"""研究架构的轻量导入边界检查。"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src/county_research_ai"


def imports_under(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*.py") if root.exists() else []:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
    return names


def test_domain_has_no_outward_dependencies():
    imports = imports_under(SRC / "domain")
    assert not any(name.endswith(("config", "agent")) or name == "click" for name in imports)


def test_application_does_not_import_concrete_adapters():
    imports = imports_under(SRC / "application")
    assert not any(name.endswith(("web_search", "local_fs", "llm.client")) for name in imports)
