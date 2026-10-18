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
    fact_accuracy: float | None
    key_fact_coverage: float | None
    evidence_support_rate: float | None
    total_ground_truth_claims: int
    verifiable_claims: int
    unverified_claims: int
    supported_claims: int
    unmatched_claims: int = 0
    error_counts: dict[str, int] = field(default_factory=dict)
    error_rate: float | None = None
    analysis_depth: float | None = None
    report_qa_accuracy: float | None = None
    fact_precision: float | None = None
    ground_truth_recall: float | None = None
    factual_error_rate: float | None = None
    unverifiable_rate: float | None = None
    report_claim_count: int = 0
    verifiable_report_claims: int = 0

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
            "fact_precision": self.fact_precision,
            "ground_truth_recall": self.ground_truth_recall,
            "factual_error_rate": self.factual_error_rate,
            "unverifiable_rate": self.unverifiable_rate,
            "report_claim_count": self.report_claim_count,
            "verifiable_report_claims": self.verifiable_report_claims,
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
        all_evaluations = list(evaluations)
        relevant = [by_id[claim_id] for claim_id in gt_ids if claim_id in by_id]
        truth_determined = [
            evaluation
            for evaluation in all_evaluations
            if evaluation.status in {ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED}
        ]
        supported = [
            evaluation
            for evaluation in all_evaluations
            if evaluation.status is ClaimStatus.SUPPORTED
        ]
        matched_supported = [
            evaluation for evaluation in relevant if evaluation.status is ClaimStatus.SUPPORTED
        ]
        ground_truth_determined = [
            evaluation
            for evaluation in relevant
            if evaluation.status in {ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED}
        ]
        evidence_candidates = [
            evaluation
            for evaluation in all_evaluations
            if evaluation.status not in {ClaimStatus.UNVERIFIED, ClaimStatus.DISPUTED}
        ]
        unverifiable = [
            evaluation
            for evaluation in all_evaluations
            if evaluation.status in {
                ClaimStatus.UNSUPPORTED,
                ClaimStatus.UNVERIFIED,
                ClaimStatus.DISPUTED,
            }
        ]
        errors = Counter(
            error_type
            for evaluation in all_evaluations
            for error_type in evaluation.error_types
        )
        verifiable_count = len(
            [
                evaluation
                for evaluation in relevant
                if evaluation.status in {ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED}
            ]
        )
        precision_denominator = len(truth_determined)
        factual_error_count = sum(
            1 for evaluation in truth_determined if evaluation.status is ClaimStatus.CONTRADICTED
        )
        fact_precision = (
            len(supported) / precision_denominator if precision_denominator else None
        )
        factual_error_rate = (
            factual_error_count / precision_denominator if precision_denominator else None
        )
        ground_truth_recall = (
            len(matched_supported) / len(gt_ids)
            if gt_ids and ground_truth_determined
            else None
        )
        evidence_support_rate = (
            sum(1 for evaluation in evidence_candidates if evaluation.evidence_supported)
            / len(evidence_candidates)
            if evidence_candidates
            else None
        )
        return MetricsResult(
            fact_accuracy=fact_precision,
            key_fact_coverage=ground_truth_recall,
            evidence_support_rate=evidence_support_rate,
            total_ground_truth_claims=len(gt_ids),
            verifiable_claims=verifiable_count,
            unverified_claims=sum(
                1 for evaluation in relevant if evaluation.status is ClaimStatus.UNVERIFIED
            ),
            supported_claims=len(matched_supported),
            unmatched_claims=sum(
                1 for evaluation in all_evaluations if evaluation.claim_id not in gt_ids
            ),
            error_counts=dict(sorted(errors.items())),
            error_rate=factual_error_rate,
            fact_precision=fact_precision,
            ground_truth_recall=ground_truth_recall,
            factual_error_rate=factual_error_rate,
            unverifiable_rate=(
                len(unverifiable) / len(all_evaluations) if all_evaluations else None
            ),
            report_claim_count=len(all_evaluations),
            verifiable_report_claims=precision_denominator,
        )
