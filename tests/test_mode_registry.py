from county_research_ai.application.context import ResearchContext
from county_research_ai.domain.research_contracts import EvidencePack, SourceDocument
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
        return "德清县工业增加值为722.5亿元。"


class LongHistoryRenderer:
    def render(self, analysis, raw_docs):
        return "德清县工业增加值为722.5亿元。"


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


def test_snapshot_report_exposes_evidence_pack_audit():
    context = _context().model_copy(
        update={
            "evidence_pack": EvidencePack(
                research_slot={"slot_id": "snapshot:overview", "research_question": "概览"},
                source_map={
                    "source-1": SourceDocument(
                        doc_id="source-1",
                        canonical_url="https://example.gov.cn/report",
                        source_title="政府公报",
                    )
                },
                token_budget=100,
                status="partial",
                missing_requirements=["工业增加值"],
            )
        }
    )

    rendered = SnapshotModeHandler(SnapshotAnalyzer(), SnapshotRenderer()).render(context)

    assert "Evidence-First" in rendered.markdown
    assert "工业增加值" in rendered.markdown
    assert "https://example.gov.cn/report" in rendered.markdown


def test_snapshot_render_marks_unsupported_numeric_claim():
    context = _context().model_copy(
        update={
            "snapshot_analyses": [
                AnalysisResult(task="industry_status", content="安吉县GDP为722.5亿元。")
            ],
            "evidence_pack": EvidencePack(
                research_slot={"slot_id": "snapshot:overview", "research_question": "概览"},
                token_budget=100,
                status="empty",
            ),
        }
    )

    rendered = SnapshotModeHandler(SnapshotAnalyzer(), SnapshotRenderer()).render(context)

    assert "未找到匹配的指标、数值和来源证据" in rendered.report.analyses[0].content


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


def test_long_history_handler_uses_requested_checkpoint_path():
    checkpoint_path = "C:/runs/long-history-checkpoint.json"
    context = _context().model_copy(
        update={
            "request": ResearchRequest(
                county="安吉县",
                mode="long-history",
                options={"analysis_checkpoint_path": checkpoint_path},
            )
        }
    )

    class CheckpointableAnalyzer(LongHistoryAnalyzer):
        def __init__(self, path=None):
            self.path = path

        def with_checkpoint(self, path):
            return CheckpointableAnalyzer(path)

        def analyze(self, county, data):
            return CountyLongHistoryAnalysis(
                county=county,
                summary=self.path or "checkpoint not configured",
            )

    result = LongHistoryModeHandler(
        CheckpointableAnalyzer(), LongHistoryRenderer()
    ).analyze(context)

    assert result.long_history_analysis.summary == checkpoint_path


def test_long_history_report_audits_all_period_packs():
    context = _context().model_copy(
        update={"request": ResearchRequest(county="安吉县", mode="long-history")}
    )
    pack_a = EvidencePack(
        research_slot={"slot_id": "history:modern", "research_question": "近代", "time_period": "1840-1948"},
        source_map={"a": SourceDocument(doc_id="a", canonical_url="https://example.gov.cn/a")},
        token_budget=100,
        status="partial",
        missing_requirements=["近代工业"],
    )
    pack_b = EvidencePack(
        research_slot={"slot_id": "history:reform", "research_question": "改革开放", "time_period": "1978-2000"},
        source_map={"b": SourceDocument(doc_id="b", canonical_url="https://example.gov.cn/b")},
        token_budget=100,
        status="complete",
    )

    class PeriodPackAnalyzer(LongHistoryAnalyzer):
        def analyze(self, county, data):
            return CountyLongHistoryAnalysis(county=county, evidence_packs=[pack_a, pack_b])

    handler = LongHistoryModeHandler(PeriodPackAnalyzer(), LongHistoryRenderer())
    analyzed = handler.analyze(context)
    rendered = handler.render(analyzed)

    assert len(analyzed.evidence_packs) == 2
    assert "history:modern（1840-1948）" in rendered.markdown
    assert "history:reform（1978-2000）" in rendered.markdown
    assert "https://example.gov.cn/a" in rendered.markdown
    assert "https://example.gov.cn/b" in rendered.markdown


def test_rise_fall_and_long_history_renderers_audit_numeric_claims():
    for mode, handler in (
        ("rise-fall", RiseFallModeHandler(RiseFallAnalyzer(), RiseFallRenderer())),
        ("long-history", LongHistoryModeHandler(LongHistoryAnalyzer(), LongHistoryRenderer())),
    ):
        context = _context().model_copy(
            update={
                "request": ResearchRequest(county="德清县", mode=mode),
                "evidence_pack": EvidencePack(
                    research_slot={"slot_id": f"{mode}:overview", "research_question": "概览"},
                    token_budget=100,
                    status="empty",
                ),
            }
        )

        rendered = handler.render(context)

        assert "未找到匹配的指标、数值和来源证据" in rendered.markdown
