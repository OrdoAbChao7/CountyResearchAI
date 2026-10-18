"""Ground Truth 评分阶段的声明级 Claim Verifier 契约。"""
from __future__ import annotations

import json
from typing import Any

from .ground_truth import GroundTruthClaim
from .metrics import ClaimEvaluation, ClaimStatus


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
        f"Claim 元数据：region={claim.region}; metric={claim.metric}; unit={claim.unit}; date={claim.date}\n"
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
