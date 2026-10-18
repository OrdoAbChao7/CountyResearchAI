from __future__ import annotations

import pytest

from county_research_ai.evaluation.metrics import (
    ClaimEvaluation,
    ClaimStatus,
    MetricsCalculator,
)


def test_metrics_calculate_claim_accuracy_coverage_and_error_types():
    ground_truth = ["fact-1", "fact-2", "fact-3"]
    evaluations = [
        ClaimEvaluation("fact-1", ClaimStatus.SUPPORTED, evidence_supported=True),
        ClaimEvaluation("fact-2", ClaimStatus.CONTRADICTED, error_types=("metric_scope",)),
        ClaimEvaluation("fact-3", ClaimStatus.UNSUPPORTED, error_types=("no_source",)),
    ]

    result = MetricsCalculator.calculate(ground_truth, evaluations)

    assert result.fact_accuracy == pytest.approx(1 / 3)
    assert result.key_fact_coverage == pytest.approx(1 / 3)
    assert result.evidence_support_rate == pytest.approx(1 / 3)
    assert result.error_rate == pytest.approx(2 / 3)
    assert result.error_counts == {"metric_scope": 1, "no_source": 1}


def test_metrics_do_not_divide_by_zero_for_empty_reports():
    result = MetricsCalculator.calculate([], [])

    assert result.fact_accuracy == 0.0
    assert result.key_fact_coverage == 0.0
    assert result.evidence_support_rate == 0.0


def test_metrics_keep_unknown_claims_out_of_accuracy_denominator_when_not_verifiable():
    evaluations = [ClaimEvaluation("fact-1", ClaimStatus.UNVERIFIED)]

    result = MetricsCalculator.calculate(["fact-1"], evaluations)

    assert result.fact_accuracy == 0.0
    assert result.verifiable_claims == 0
    assert result.unverified_claims == 1


def test_metrics_count_claims_outside_ground_truth_as_unmatched():
    result = MetricsCalculator.calculate(
        ["gt-1"],
        [
            ClaimEvaluation("gt-1", ClaimStatus.SUPPORTED, evidence_supported=True),
            ClaimEvaluation("hallucination-1", ClaimStatus.UNSUPPORTED, error_types=("NO_SOURCE",)),
        ],
    )

    assert result.unmatched_claims == 1
    assert result.error_counts == {"NO_SOURCE": 1}


def test_metrics_reject_duplicate_evaluations():
    with pytest.raises(ValueError, match="duplicate claim_id"):
        MetricsCalculator.calculate(
            ["gt-1"],
            [
                ClaimEvaluation("gt-1", ClaimStatus.SUPPORTED),
                ClaimEvaluation("gt-1", ClaimStatus.CONTRADICTED),
            ],
        )
