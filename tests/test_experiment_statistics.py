from __future__ import annotations

import pytest

from county_research_ai.evaluation.metrics import MetricsResult
from county_research_ai.evaluation.statistics import (
    MetricObservation,
    paired_difference,
    summarize_observations,
    summarize_observations_by_region,
)


def _metrics(fact_accuracy: float, coverage: float) -> MetricsResult:
    return MetricsResult(
        fact_accuracy=fact_accuracy,
        key_fact_coverage=coverage,
        evidence_support_rate=0.5,
        total_ground_truth_claims=4,
        verifiable_claims=4,
        unverified_claims=0,
        supported_claims=2,
        error_rate=0.25,
        analysis_depth=0.75,
        report_qa_accuracy=1.0,
    )


def test_statistics_reports_mean_median_and_wide_small_sample_interval():
    observations = [
        MetricObservation("a-1", "A", "甲县", "snapshot", 1, _metrics(0.2, 0.3)),
        MetricObservation("a-2", "A", "甲县", "snapshot", 2, _metrics(0.8, 0.7)),
    ]

    rows = summarize_observations(observations)
    fact = next(row for row in rows if row.metric == "fact_accuracy")

    assert fact.group == "A"
    assert fact.n == 2
    assert fact.mean == pytest.approx(0.5)
    assert fact.median == pytest.approx(0.5)
    assert fact.ci95_low < fact.mean < fact.ci95_high


def test_paired_difference_matches_same_region_task_and_repeat():
    observations = [
        MetricObservation("a-1", "A", "甲县", "snapshot", 1, _metrics(0.4, 0.3)),
        MetricObservation("c-1", "C", "甲县", "snapshot", 1, _metrics(0.8, 0.6)),
        MetricObservation("a-other", "A", "乙县", "snapshot", 1, _metrics(0.1, 0.1)),
    ]

    result = paired_difference(observations, left_group="C", right_group="A", metric="fact_accuracy")

    assert result.n == 1
    assert result.mean_difference == pytest.approx(0.4)


def test_statistics_rejects_unknown_metric():
    observations = [
        MetricObservation("run", "A", "甲县", "snapshot", 1, _metrics(0.2, 0.3))
    ]

    with pytest.raises(ValueError, match="unknown metric"):
        summarize_observations(observations, metrics=("not_a_metric",))


def test_statistics_includes_judge_qa_and_resource_metrics_when_present():
    observation = MetricObservation(
        "run",
        "C",
        "甲县",
        "snapshot",
        1,
        _metrics(0.8, 0.6),
        duration_seconds=12.5,
        resource_usage={"gemini:model:llm": 1000, "tavily:search:search": 3},
    )

    rows = summarize_observations([observation])
    values = {row.metric: row.mean for row in rows}

    assert values["analysis_depth"] == pytest.approx(0.75)
    assert values["report_qa_accuracy"] == pytest.approx(1.0)
    assert values["duration_seconds"] == pytest.approx(12.5)
    assert values["llm_tokens"] == pytest.approx(1000)
    assert values["search_requests"] == pytest.approx(3)
    assert values["coverage_per_llm_token"] == pytest.approx(0.0006)


def test_region_statistics_preserve_region_and_group_breakdown():
    observations = [
        MetricObservation("a-1", "A", "甲县", "snapshot", 1, _metrics(0.2, 0.3)),
        MetricObservation("c-1", "C", "甲县", "snapshot", 1, _metrics(0.8, 0.7)),
        MetricObservation("a-2", "A", "乙县", "snapshot", 1, _metrics(0.4, 0.5)),
    ]

    rows = summarize_observations_by_region(observations)
    fact = next(
        row for row in rows if row.region == "甲县" and row.group == "C" and row.metric == "fact_accuracy"
    )

    assert fact.n == 1
    assert fact.mean == pytest.approx(0.8)
