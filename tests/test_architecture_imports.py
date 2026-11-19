"""V2 架构导入边界检查。"""
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
    forbidden = (
        "county_research_ai.agents",
        "county_research_ai.api",
        "county_research_ai.bootstrap",
        "county_research_ai.infrastructure",
        "county_research_ai.knowledge_graph",
        "county_research_ai.orchestration",
        "county_research_ai.services",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_agents_do_not_depend_on_orchestration_or_api():
    imports = imports_under(SRC / "agents")
    assert not any(
        name.startswith(("county_research_ai.orchestration", "county_research_ai.api"))
        for name in imports
    )


def test_knowledge_graph_is_independent_of_agents_and_orchestration():
    imports = imports_under(SRC / "knowledge_graph")
    assert not any(
        name.startswith(
            (
                "county_research_ai.agents",
                "county_research_ai.api",
                "county_research_ai.orchestration",
            )
        )
        for name in imports
    )


def test_services_do_not_depend_on_api_or_orchestration():
    imports = imports_under(SRC / "services")
    assert not any(
        name.startswith(
            (
                "county_research_ai.agents",
                "county_research_ai.api",
                "county_research_ai.orchestration",
            )
        )
        for name in imports
    )


def test_no_legacy_workflow_modules_remain():
    for relative in (
        "cli.py",
        "pipeline.py",
        "application",
        "modes",
        "agent",
        "research_agent",
        "interfaces",
    ):
        assert not (SRC / relative).exists(), f"legacy module still present: {relative}"


def test_no_pipeline_config_imports_remain():
    imports = imports_under(SRC)
    assert not any("PipelineConfig" in name for name in imports)
    source_hits: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "settings.pipeline" in text or "PipelineRunner" in text:
            source_hits.append(str(path))
    assert source_hits == []
