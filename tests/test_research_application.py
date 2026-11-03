from __future__ import annotations

from pathlib import Path

import pytest

from county_research_ai.application.config import ResearchApplicationConfig
from county_research_ai.application.context import ResearchContext
from county_research_ai.application.research import ResearchApplication
from county_research_ai.exceptions import ResearchStageError
from county_research_ai.models import (
    AnalysisResult,
    DiscoveryResult,
    ProcessedData,
    RawDoc,
    ReportSection,
    ResearchReport,
    ResearchRequest,
)
from county_research_ai.modes.base import RenderedReport
from county_research_ai.modes.registry import ModeRegistry


class StaticSearch:
    def __init__(self, docs):
        self.docs = docs
        self.modes = []

    def collect(self, county, focus, max_results, *, mode):
        self.modes.append(mode)
        return self.docs


class StaticDiscovery:
    def __init__(self, result=None):
        self.result = result or DiscoveryResult()

    def discover_focus(self, *, county, raw_docs):
        return self.result


class StaticProcessor:
    def process(self, raw_docs, *, county, focus):
        return ProcessedData(county=county, focus=focus, docs=raw_docs)


class StaticStorage:
    def __init__(self, root: Path):
        self.root = root
        self.load_calls = 0
        self.saved_processed = []

    def save_raw(self, county, docs):
        path = self.root / "raw.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raw", encoding="utf-8")
        return path

    def load_processed(self, county, focus, max_age_hours=0):
        self.load_calls += 1
        return None

    def save_processed(self, county, focus, data):
        self.saved_processed.append((county, focus))
        path = self.root / "processed.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data.model_dump_json(), encoding="utf-8")
        return path

    def save_report(self, filename, content):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class SnapshotHandler:
    name = "snapshot"
    default_focus = "特色农业"

    def analyze(self, context):
        return context.model_copy(
            update={"snapshot_analyses": [AnalysisResult(task="status", content="ok")]}
        )

    def render(self, context):
        report = ResearchReport(
            county=context.county,
            focus=context.focus,
            sections=[ReportSection(title="执行摘要", content="ok", order=1)],
        )
        return RenderedReport(report=report, markdown="# report")


def make_application(tmp_path, *, docs=None, discovery=None, storage=None):
    search = StaticSearch(docs or [RawDoc(title="材料", url="https://example.com")])
    storage = storage or StaticStorage(tmp_path)
    config = ResearchApplicationConfig(
        max_search_results=10,
        cache_enabled=True,
        cache_ttl_hours=24,
        report_filename_template="{{ county }}_{{ focus }}_{{ date }}.md",
    )
    return (
        ResearchApplication(
            search=search,
            storage=storage,
            processor=StaticProcessor(),
            discovery=discovery or StaticDiscovery(),
            modes=ModeRegistry([SnapshotHandler()]),
            config=config,
            render_filename=lambda template, values: f"{values['county']}_{values['focus']}.md",
        ),
        search,
        storage,
    )


def test_application_runs_each_stage_and_writes_report(tmp_path):
    application, search, storage = make_application(tmp_path)
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", mode="snapshot")
    )

    context = application.collect_materials(context)
    assert context.raw_docs
    context = application.discover_focus(context)
    assert context.focus == "特色农业"
    context = application.build_evidence(context)
    assert context.processed is not None
    context = application.analyze(context)
    assert context.snapshot_analyses
    result = application.render_report(context)

    assert result.report_path.exists()
    assert result.report.county.name == "安吉县"
    assert search.modes == ["snapshot"]
    assert storage.saved_processed == [("安吉县", "特色农业")]


def test_empty_search_without_focus_uses_handler_default(tmp_path):
    application, _, _ = make_application(tmp_path, docs=[])
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", mode="snapshot")
    )

    context = application.discover_focus(application.collect_materials(context))

    assert context.focus == "特色农业"
    assert context.request.focus == "特色农业"


def test_no_cache_skips_storage_cache_lookup(tmp_path):
    storage = StaticStorage(tmp_path)
    application, _, storage = make_application(tmp_path, storage=storage)
    context = ResearchContext.from_request(
        ResearchRequest(
            county="安吉县",
            focus="竹产业",
            mode="snapshot",
            options={"no_cache": True},
        )
    )

    application.build_evidence(application.collect_materials(context))

    assert storage.load_calls == 0


def test_provider_failure_becomes_safe_retryable_stage_error(tmp_path):
    class RateLimitError(Exception):
        status_code = 429

    class FailingProcessor:
        def process(self, raw_docs, *, county, focus):
            raise RateLimitError("provider key=secret")

    application, _, _ = make_application(tmp_path)
    application.processor = FailingProcessor()
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )
    context = application.collect_materials(context)

    with pytest.raises(ResearchStageError) as caught:
        application.build_evidence(context)

    error = caught.value
    assert error.stage == "process"
    assert error.retryable is True
    assert isinstance(error.__cause__, RateLimitError)
    assert "secret" not in str(error)
