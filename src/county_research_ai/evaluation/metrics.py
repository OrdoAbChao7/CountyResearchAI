"""声明级研究质量指标。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"
    DISPUTED = "DISPUTED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class ClaimEvaluation:
    claim_id: str
    status: ClaimStatus
    evidence_supported: bool = False
    error_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricsResult:
    fact_accuracy: float
    key_fact_coverage: float
    evidence_support_rate: float
    total_ground_truth_claims: int
    verifiable_claims: int
    unverified_claims: int
    supported_claims: int
    unmatched_claims: int = 0
    error_counts: dict[str, int] = field(default_factory=dict)
    error_rate: float = 0.0
    analysis_depth: float | None = None
    report_qa_accuracy: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_accuracy": self.fact_accuracy,
            "key_fact_coverage": self.key_fact_coverage,
            "evidence_support_rate": self.evidence_support_rate,
            "total_ground_truth_claims": self.total_ground_truth_claims,
            "verifiable_claims": self.verifiable_claims,
            "unverified_claims": self.unverified_claims,
            "supported_claims": self.supported_claims,
            "unmatched_claims": self.unmatched_claims,
            "error_counts": dict(self.error_counts),
            "error_rate": self.error_rate,
            "analysis_depth": self.analysis_depth,
            "report_qa_accuracy": self.report_qa_accuracy,
        }


class MetricsCalculator:
    @staticmethod
    def calculate(
        ground_truth_claim_ids: list[str], evaluations: list[ClaimEvaluation]
    ) -> MetricsResult:
        gt_ids = set(ground_truth_claim_ids)
        by_id: dict[str, ClaimEvaluation] = {}
        for evaluation in evaluations:
            if evaluation.claim_id in by_id:
                raise ValueError(f"duplicate claim_id: {evaluation.claim_id}")
            by_id[evaluation.claim_id] = evaluation
        relevant = [by_id[claim_id] for claim_id in gt_ids if claim_id in by_id]
        verifiable = [
            evaluation
            for evaluation in relevant
            if evaluation.status is not ClaimStatus.UNVERIFIED
        ]
        supported = [
            evaluation for evaluation in relevant if evaluation.status is ClaimStatus.SUPPORTED
        ]
        errors = Counter(
            error_type
            for evaluation in evaluations
            for error_type in evaluation.error_types
        )
        verifiable_count = len(verifiable)
        error_claims = sum(
            1
            for evaluation in verifiable
            if evaluation.status in {ClaimStatus.CONTRADICTED, ClaimStatus.UNSUPPORTED}
            or evaluation.error_types
        )
        return MetricsResult(
            fact_accuracy=len(supported) / verifiable_count if verifiable_count else 0.0,
            key_fact_coverage=len(supported) / len(gt_ids) if gt_ids else 0.0,
            evidence_support_rate=(
                sum(1 for evaluation in verifiable if evaluation.evidence_supported)
                / verifiable_count
                if verifiable_count
                else 0.0
            ),
            total_ground_truth_claims=len(gt_ids),
            verifiable_claims=verifiable_count,
            unverified_claims=sum(
                1 for evaluation in relevant if evaluation.status is ClaimStatus.UNVERIFIED
            ),
            supported_claims=len(supported),
            unmatched_claims=sum(1 for evaluation in evaluations if evaluation.claim_id not in gt_ids),
            error_counts=dict(sorted(errors.items())),
            error_rate=error_claims / verifiable_count if verifiable_count else 0.0,
        )
