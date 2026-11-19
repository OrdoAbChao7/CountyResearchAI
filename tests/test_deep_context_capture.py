"""深度研究结果必须随运行上下文透出，供 Web 层投影使用。"""
from __future__ import annotations

from types import SimpleNamespace

from county_research_ai.application.context import ResearchContext
from county_research_ai.models import ResearchRequest
from county_research_ai.modes.long_history import LongHistoryModeHandler
from county_research_ai.modes.rise_fall import RiseFallModeHandler
from county_research_ai.modes.snapshot import SnapshotModeHandler
from county_research_ai.research_agent.coordinator import DeepResearchCoordinator


def _deep_context(processed, *, focus: str = "竹产业") -> ResearchContext:
    context = ResearchContext.from_request(
        ResearchRequest(
            county="安吉县",
            focus=focus,
            options={"deep_research": True},
        )
    )
    return context.model_copy(update={"processed": processed})


def _fake_result(**overrides):
    payload = {
        "analyses": [],
        "rise_fall_analysis": None,
        "long_history_analysis": None,
        "all_raw_docs": [],
        "evidence_packs": [],
        "research_spec": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _patch_coordinator(monkeypatch, result):
    calls: list[dict] = []

    def fake_run(self, **kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(DeepResearchCoordinator, "run_deep_research", fake_run)
    return calls


def test_snapshot_handler_captures_deep_result(
    monkeypatch, sample_processed_data
) -> None:
    sentinel = _fake_result()
    calls = _patch_coordinator(monkeypatch, sentinel)
    handler = SnapshotModeHandler(analyzer=None, renderer=None, search=None)

    updated = handler.analyze(_deep_context(sample_processed_data))

    assert updated.deep_research is sentinel
    assert calls[0]["mode"] == "snapshot"
    assert calls[0]["county"] == "安吉县"


def test_rise_fall_handler_captures_deep_result(
    monkeypatch, sample_processed_data
) -> None:
    sentinel = _fake_result()
    calls = _patch_coordinator(monkeypatch, sentinel)
    handler = RiseFallModeHandler(analyzer=None, renderer=None, search=None)

    updated = handler.analyze(_deep_context(sample_processed_data))

    assert updated.deep_research is sentinel
    assert calls[0]["mode"] == "rise-fall"


def test_long_history_handler_captures_deep_result(
    monkeypatch, sample_processed_data
) -> None:
    sentinel = _fake_result()
    calls = _patch_coordinator(monkeypatch, sentinel)
    handler = LongHistoryModeHandler(analyzer=None, renderer=None, search=None)

    updated = handler.analyze(_deep_context(sample_processed_data))

    assert updated.deep_research is sentinel
    assert calls[0]["mode"] == "long-history"


def test_non_deep_path_leaves_deep_result_empty(sample_processed_data) -> None:
    class StubAnalyzer:
        def analyze(self, **kwargs):
            return []

    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", focus="竹产业")
    ).model_copy(update={"processed": sample_processed_data})
    handler = SnapshotModeHandler(analyzer=StubAnalyzer(), renderer=None, search=None)

    updated = handler.analyze(context)

    assert updated.deep_research is None


def test_deep_result_is_excluded_from_serialisation(sample_processed_data) -> None:
    context = _deep_context(sample_processed_data).model_copy(
        update={"deep_research": object()}
    )

    assert "deep_research" not in context.model_dump()
