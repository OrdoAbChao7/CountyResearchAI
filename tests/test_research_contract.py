"""研究入口的兼容性契约测试。"""
from __future__ import annotations

import pytest

from county_research_ai.config import reset_settings
from county_research_ai.models import ResearchRequest
from county_research_ai.pipeline import create_default_pipeline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_settings()
    yield tmp_path
    reset_settings()


def test_pipeline_does_not_mutate_request_mode(isolated_env):
    request = ResearchRequest(county="安吉县", focus="竹产业", mode="industry")

    create_default_pipeline().run(request)

    assert request.mode == "industry"


@pytest.mark.parametrize(
    ("mode", "focus"),
    [("snapshot", "竹产业"), ("rise-fall", None), ("long-history", None)],
)
def test_all_modes_preserve_report_contract(isolated_env, mode, focus):
    request = ResearchRequest(county="安吉县", focus=focus, mode=mode)
    report, path = create_default_pipeline().run(request)

    assert path.exists()
    assert report.county.name == "安吉县"
    assert "安吉县" in path.read_text(encoding="utf-8")
