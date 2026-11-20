"""Adaptive rounds must expose target-period coverage and real query text."""
from __future__ import annotations

from types import SimpleNamespace

from county_research_ai.observability import bind_event_sink
from county_research_ai.research_agent.coordinator import DeepResearchCoordinator


class RecordingSink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, draft) -> None:
        self.events.append(draft)


class EmptyAdaptiveCollector:
    def collect_adaptive(self, plan, *, controller=None):
        return SimpleNamespace(
            documents=(),
            usage={"search_queries": len(plan.queries)},
        )


def test_adaptive_round_records_period_coverage_and_query_text():
    sink = RecordingSink()
    with bind_event_sink(sink):
        result = DeepResearchCoordinator(
            search_collector=EmptyAdaptiveCollector(),
            max_turns=1,
        ).run_deep_research(
            "安吉县",
            "竹产业",
            "snapshot",
            target_years=["2024"],
            time_period="2024",
        )

    period_events = [
        event for event in sink.events if event.type == "retrieval.period_coverage"
    ]
    assert period_events
    payload = period_events[0].payload
    assert payload["round"] == 1
    assert payload["target_years"] == ["2024"]
    assert payload["topic_coverage_met"] is False
    assert payload["period_coverage_met"] is False
    assert payload["in_window_claim_count"] == 0

    started = [
        event for event in sink.events if event.type == "retrieval.round.started"
    ]
    query_texts = [
        text for event in started for text in event.payload.get("query_texts", [])
    ]
    assert any("2024年" in text for text in query_texts), query_texts

    assert result.period_coverage["in_window_claim_count"] == 0
    assert result.period_coverage_history[0]["round"] == 1
    assert result.retrieval_stop_reason
