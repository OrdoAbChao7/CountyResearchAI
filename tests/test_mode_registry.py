from county_research_ai.application.context import ResearchContext
from county_research_ai.models import (
    AnalysisResult,
    CountyLongHistoryAnalysis,
    CountyRiseFallAnalysis,
    ProcessedData,
    ResearchRequest,
)
from county_research_ai.modes.long_history import LongHistoryModeHandler
from county_research_ai.modes.registry import ModeRegistry
from county_research_ai.modes.rise_fall import RiseFallModeHandler
from county_research_ai.modes.snapshot import SnapshotModeHandler


class StubHandler:
    name = "snapshot"
    default_focus = "特色农业"


def test_registry_returns_registered_handler():
    handler = StubHandler()
    assert ModeRegistry([handler]).get("snapshot") is handler


def test_registry_rejects_duplicate_mode():
    try:
        ModeRegistry([StubHandler(), StubHandler()])
    except ValueError as exc:
        assert "duplicate research mode" in str(exc)
    else:
        raise AssertionError("duplicate mode was accepted")


def test_registry_rejects_unknown_mode():
    try:
        ModeRegistry([StubHandler()]).get("long-history")
    except ValueError as exc:
        assert "unsupported research mode" in str(exc)
    else:
        raise AssertionError("unknown mode was accepted")


class SnapshotAnalyzer:
    def analyze(self, county, focus, data):
        return [AnalysisResult(task="industry_status", content="ok")]

    def generate_summary(self, county, focus, analyses):
        return "summary"


class RiseFallAnalyzer:
    def analyze(self, county, data):
        return CountyRiseFallAnalysis(county=county)


class LongHistoryAnalyzer:
    def analyze(self, county, data):
        return CountyLongHistoryAnalysis(county=county)


class SnapshotRenderer:
    def render_markdown(self, report):
        return "snapshot markdown"


class RiseFallRenderer:
    def render(self, analysis, raw_docs):
        return "rise-fall markdown"


class LongHistoryRenderer:
    def render(self, analysis, raw_docs):
        return "long-history markdown"


def _context():
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )
    return context.model_copy(
        update={
            "processed": ProcessedData(
                county=context.county,
                focus="竹产业",
                docs=[],
            )
        }
    )


def test_snapshot_handler_updates_only_snapshot_analysis():
    result = SnapshotModeHandler(SnapshotAnalyzer(), SnapshotRenderer()).analyze(_context())

    assert result.snapshot_analyses
    assert result.rise_fall_analysis is None
    assert result.long_history_analysis is None


def test_rise_fall_handler_updates_only_rise_fall_analysis():
    context = _context().model_copy(update={"request": ResearchRequest(county="安吉县", mode="rise-fall")})
    result = RiseFallModeHandler(RiseFallAnalyzer(), RiseFallRenderer()).analyze(context)

    assert result.rise_fall_analysis is not None
    assert result.snapshot_analyses == []
    assert result.long_history_analysis is None


def test_long_history_handler_updates_only_long_history_analysis():
    context = _context().model_copy(update={"request": ResearchRequest(county="安吉县", mode="long-history")})
    result = LongHistoryModeHandler(LongHistoryAnalyzer(), LongHistoryRenderer()).analyze(context)

    assert result.long_history_analysis is not None
    assert result.snapshot_analyses == []
    assert result.rise_fall_analysis is None
