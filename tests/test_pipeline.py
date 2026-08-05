"""Pipeline 集成测试(Mock 降级链路)。

不依赖真实 API Key,测试 create_default_pipeline 自动降级 + run 全流程。
用 monkeypatch 设置临时 DATA_DIR/REPORTS_DIR,不污染项目目录。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from county_research_ai.config import reset_settings
from county_research_ai.models import ResearchRequest
from county_research_ai.pipeline import (
    MockLLMClient,
    MockSearchProvider,
    create_default_pipeline,
)


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """设置临时数据/报告目录,避免污染项目。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_settings()
    yield tmp_path
    reset_settings()


class TestCreateDefaultPipeline:
    def test_no_key_uses_mock_search(self, isolated_env):
        pipeline = create_default_pipeline()
        assert isinstance(pipeline.search, MockSearchProvider)

    def test_no_key_uses_mock_llm(self, isolated_env):
        pipeline = create_default_pipeline()
        assert isinstance(pipeline.llm, MockLLMClient)

    def test_pipeline_has_storage(self, isolated_env):
        pipeline = create_default_pipeline()
        assert pipeline.storage is not None

    def test_pipeline_has_analyzer(self, isolated_env):
        pipeline = create_default_pipeline()
        assert pipeline.analyzer is not None


class TestPipelineRun:
    def test_run_produces_report(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        report, report_path = pipeline.run(request)
        assert report is not None
        assert report_path is not None

    def test_report_has_sections(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        report, _ = pipeline.run(request)
        assert report.section_count >= 4  # 摘要 + 4 章节 + 数据来源

    def test_report_file_written_to_disk(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        _, report_path = pipeline.run(request)
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "安吉县" in content
        assert "竹产业" in content

    def test_report_contains_all_analysis_sections(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        report, _ = pipeline.run(request)
        titles = [s.title for s in report.sections]
        assert "执行摘要" in titles
        assert "一、产业现状分析" in titles
        assert "二、优势分析" in titles
        assert "三、短板分析" in titles
        assert "四、发展建议" in titles
        assert "数据来源" in titles

    def test_raw_data_saved(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        pipeline.run(request)
        # raw 数据应落盘
        raw_files = list((isolated_env / "data" / "raw" / "安吉县").glob("*/raw_docs.json"))
        assert len(raw_files) >= 1

    def test_processed_data_saved(self, isolated_env):
        pipeline = create_default_pipeline()
        request = ResearchRequest(county="安吉县", focus="竹产业")
        pipeline.run(request)
        processed_file = isolated_env / "data" / "processed" / "安吉县" / "竹产业.json"
        assert processed_file.exists()

    def test_different_county_produces_different_report(self, isolated_env):
        pipeline = create_default_pipeline()
        _, path1 = pipeline.run(ResearchRequest(county="安吉县", focus="竹产业"))
        _, path2 = pipeline.run(ResearchRequest(county="德清县", focus="通航产业"))
        assert path1 != path2
        assert "安吉县" in str(path1)
        assert "德清县" in str(path2)
