"""Ground Truth 评分阶段的声明级 Claim Verifier 契约。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .ground_truth import GroundTruthClaim
from .metrics import ClaimEvaluation, ClaimStatus


@dataclass(frozen=True)
class DeterministicClaimCheck:
    """结构化事实可以直接核验时的离线检查结果。"""

    evaluation: ClaimEvaluation
    reason: str
    checks: dict[str, bool]


_DISPUTE_MARKERS = ("争议", "口径不一", "存在冲突", "disputed", "conflict")
_SCOPE_MARKERS = ("县域本级", "全市", "市域", "全县", "全区", "全省", "全国")


def deterministic_claim_check(
    *,
    report: str,
    source_material: str,
    claim: GroundTruthClaim,
) -> DeterministicClaimCheck | None:
    """在调用语义 Judge 前核验明确的数字、时间、单位和行政范围。

    该检查只处理有结构化信号的 Claim；没有数字、日期、单位或范围信号时返回
    ``None``，由后续语义 Judge 处理。它不读取其他实验组数据，也不进行网络调用。
    """
    expected_text = claim.expected_answer.strip() or claim.claim
    expected_years = set(
        re.findall(
            r"(?:19|20)\d{2}",
            " ".join(
                (
                    expected_text,
                    claim.metric_year or claim.date or claim.source_date,
                )
            ),
        )
    )
    expected_numbers = [
        _normalize_number(value)
        for value in re.findall(r"\d+(?:[,.]\d+)?%?", expected_text)
        if value not in expected_years
    ]
    expected_unit = claim.unit.strip()
    expected_scope = (claim.administrative_scope.strip() or claim.region.strip())
    structured_signal = bool(expected_numbers or expected_years or expected_unit or expected_scope)
    if not structured_signal:
        return None

    report = report or ""
    source_material = source_material or ""
    report_relevant = _is_relevant(report, claim)
    source_relevant = _is_relevant(source_material, claim)
    combined = f"{report}\n{source_material}"
    if any(marker.casefold() in combined.casefold() for marker in _DISPUTE_MARKERS):
        evaluation = ClaimEvaluation(
            claim_id=claim.claim_id,
            status=ClaimStatus.DISPUTED,
            evidence_supported=False,
            error_types=("disputed_source",),
        )
        return DeterministicClaimCheck(
            evaluation=evaluation,
            reason="来源材料明确标记为争议或口径冲突，不能直接判定事实真值。",
            checks={"disputed": True, "report_relevant": report_relevant},
        )

    if not report.strip():
        return _check(
            claim,
            ClaimStatus.UNVERIFIED,
            ("empty_report",),
            "研究报告为空，无法核验冻结 Claim。",
            report_relevant=False,
            source_relevant=source_relevant,
        )

    report_has_numbers = _contains_all_numbers(report, expected_numbers)
    source_has_numbers = _contains_all_numbers(source_material, expected_numbers)
    report_has_years = _contains_all(report, expected_years)
    source_has_years = _contains_all(source_material, expected_years)
    report_has_unit = not expected_unit or expected_unit in report
    source_has_unit = not expected_unit or expected_unit in source_material
    report_has_scope = not expected_scope or expected_scope in report
    source_has_scope = not expected_scope or expected_scope in source_material
    source_matches = (
        source_relevant
        and source_has_numbers
        and source_has_years
        and source_has_unit
        and source_has_scope
    )
    report_matches = (
        report_relevant
        and report_has_numbers
        and report_has_years
        and report_has_unit
        and report_has_scope
    )

    if report_matches and source_matches:
        return _check(
            claim,
            ClaimStatus.SUPPORTED,
            (),
            "报告中的结构化事实与归档来源的数字、日期和单位一致。",
            report_relevant=report_relevant,
            source_relevant=source_relevant,
            report_matches=True,
            source_matches=True,
        )

    error_types: list[str] = []
    if report_relevant:
        report_numbers = {
            _normalize_number(value)
            for value in re.findall(r"\d+(?:[,.]\d+)?%?", report)
            if value not in expected_years
        }
        if expected_numbers and report_numbers and not report_has_numbers:
            error_types.append("numeric_mismatch")
        if expected_years and not report_has_years and re.search(r"(?:19|20)\d{2}", report):
            error_types.append("date_mismatch")
        if expected_unit and not report_has_unit and any(
            unit in report for unit in ("亿元", "万元", "%", "万人", "平方公里")
        ):
            error_types.append("unit_mismatch")
        if expected_scope and not report_has_scope and any(
            marker in report for marker in _SCOPE_MARKERS if marker != expected_scope
        ):
            error_types.append("scope_mismatch")
    if error_types:
        return _check(
            claim,
            ClaimStatus.CONTRADICTED,
            tuple(error_types),
            "报告包含与冻结 Claim 不一致的结构化数字、日期、单位或行政范围。",
            report_relevant=report_relevant,
            source_relevant=source_relevant,
            report_matches=report_matches,
            source_matches=source_matches,
        )

    if report_relevant or source_relevant:
        return _check(
            claim,
            ClaimStatus.UNSUPPORTED,
            ("insufficient_evidence",),
            "报告或来源提及相关主题，但没有足够结构化证据支持冻结 Claim。",
            report_relevant=report_relevant,
            source_relevant=source_relevant,
            report_matches=report_matches,
            source_matches=source_matches,
        )

    return _check(
        claim,
        ClaimStatus.UNVERIFIED,
        ("claim_not_addressed",),
        "报告和归档来源均未提及冻结 Claim 的相关主题。",
        report_relevant=False,
        source_relevant=False,
    )


def _check(
    claim: GroundTruthClaim,
    status: ClaimStatus,
    error_types: tuple[str, ...],
    reason: str,
    **checks: bool,
) -> DeterministicClaimCheck:
    return DeterministicClaimCheck(
        evaluation=ClaimEvaluation(
            claim_id=claim.claim_id,
            status=status,
            evidence_supported=status is ClaimStatus.SUPPORTED,
            error_types=error_types,
        ),
        reason=reason,
        checks=checks,
    )


def _normalize_number(value: str) -> str:
    return value.replace(",", "").replace("，", "")


def _contains_all(text: str, values: set[str]) -> bool:
    return all(value in text for value in values)


def _contains_all_numbers(text: str, values: list[str]) -> bool:
    normalized = {
        _normalize_number(value)
        for value in re.findall(r"\d+(?:[,.]\d+)?%?", text)
    }
    return all(value in normalized for value in values)


def _is_relevant(text: str, claim: GroundTruthClaim) -> bool:
    if not text.strip():
        return False
    normalized = text.casefold()
    candidates = [claim.metric, claim.region]
    if len(claim.metric.strip()) >= 2:
        candidates.append(claim.metric.strip()[:2])
    return any(candidate and candidate.casefold() in normalized for candidate in candidates)


def build_claim_verification_prompt(
    *,
    report: str,
    source_material: str,
    claim: GroundTruthClaim,
) -> str:
    return (
        "你是独立的声明级事实核验 Agent。当前已经进入 Ground Truth 评分阶段；"
        "只能依据研究报告和随报告归档的来源材料判断冻结 claim，不能读取其他实验组或运行轨迹。"
        "请区分报告没有提及、报告与 claim 矛盾、报告被来源支持和 claim 版本争议。只输出 JSON，"
        "字段为 status、evidence_supported、error_types、reason。status 必须是 "
        "SUPPORTED、CONTRADICTED、UNSUPPORTED、DISPUTED 或 UNVERIFIED。\n"
        f"冻结 Claim：{claim.claim}\n"
        f"Claim 元数据：region={claim.region}; metric={claim.metric}; unit={claim.unit}; date={claim.date}; "
        f"research_mode={claim.research_mode}; expected_answer={claim.expected_answer}; "
        f"source_title={claim.source_title}; source_date={claim.source_date}; "
        f"metric_year={claim.metric_year}; administrative_scope={claim.administrative_scope}\n"
        f"研究报告：\n{report}\n"
        f"归档来源材料：\n{source_material or '(没有来源材料)'}"
    )


def parse_claim_verification(
    content: str,
    *,
    claim_id: str,
) -> tuple[ClaimEvaluation, str]:
    try:
        value: Any = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("claim verifier response must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("claim verifier response must be an object")
    try:
        status = ClaimStatus(str(value.get("status", "")))
    except ValueError as exc:
        raise ValueError(f"unsupported claim status: {value.get('status')}") from exc
    raw_errors = value.get("error_types", [])
    if not isinstance(raw_errors, list):
        raise ValueError("claim verifier error_types must be a list")
    evidence_supported = value.get("evidence_supported", False)
    if isinstance(evidence_supported, str) and evidence_supported.lower() in {"true", "false"}:
        evidence_supported = evidence_supported.lower() == "true"
    if not isinstance(evidence_supported, bool):
        raise ValueError("claim verifier evidence_supported must be boolean")
    reason = str(value.get("reason", "")).strip()
    return (
        ClaimEvaluation(
            claim_id=claim_id,
            status=status,
            evidence_supported=evidence_supported,
            error_types=tuple(str(item) for item in raw_errors),
        ),
        reason,
    )
