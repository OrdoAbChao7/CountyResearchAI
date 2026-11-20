from __future__ import annotations

import pytest

from county_research_ai.evaluation.metrics import (
    ClaimEvaluation,
    ClaimStatus,
    MetricsCalculator,
)


def test_metrics_report_non_comparable_rate_without_polluting_error_rate():
    result = MetricsCalculator.calculate(
        ["gt-1"],
        [
            ClaimEvaluation("gt-1", ClaimStatus.NON_COMPARABLE, error_types=("unit_mismatch",)),
            ClaimEvaluation("extra-1", ClaimStatus.CONTRADICTED, error_types=("numeric_mismatch",)),
        ],
    )

    assert result.fact_precision == pytest.approx(0.0)
    assert result.factual_error_rate == pytest.approx(1.0)
    assert result.non_comparable_claims == 1
    assert result.non_comparable_rate == pytest.approx(1 / 2)
    assert result.unverifiable_rate == pytest.approx(1 / 2)
