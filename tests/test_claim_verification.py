from __future__ import annotations

import pytest

from county_research_ai.evaluation.claim_verification import (
    build_claim_verification_prompt,
    parse_claim_verification,
)
from county_research_ai.evaluation.ground_truth import GroundTruthClaim
from county_research_ai.evaluation.metrics import ClaimStatus


def _claim() -> GroundTruthClaim:
    return GroundTruthClaim(
        claim_id="claim-1",
        claim="地区生产总值为10亿元。",
        source="统计公报",
        url="https://example.gov.cn/bulletin",
        date="2024",
        region="新地区县",
        metric="地区生产总值",
        unit="亿元",
        evidence_excerpt="地区生产总值为10亿元。",
        confidence="high",
        verification_status="VERIFIED",
    )


def test_claim_verification_prompt_separates_frozen_claim_from_report():
    prompt = build_claim_verification_prompt(
        report="报告写明地区生产总值为10亿元。",
        source_material="来源正文",
        claim=_claim(),
    )

    assert "地区生产总值为10亿元" in prompt
    assert "报告写明" in prompt
    assert "只输出 JSON" in prompt


def test_parse_claim_verification_returns_declaration_level_evaluation():
    evaluation, reason = parse_claim_verification(
        '{"status":"SUPPORTED","evidence_supported":true,"error_types":[],"reason":"数字和来源匹配"}',
        claim_id="claim-1",
    )

    assert evaluation.claim_id == "claim-1"
    assert evaluation.status is ClaimStatus.SUPPORTED
    assert evaluation.evidence_supported is True
    assert reason == "数字和来源匹配"


def test_parse_claim_verification_rejects_unknown_status():
    with pytest.raises(ValueError, match="unsupported claim status"):
        parse_claim_verification(
            '{"status":"MAYBE","evidence_supported":false}',
            claim_id="claim-1",
        )


def test_parse_claim_verification_accepts_unambiguous_boolean_strings():
    evaluation, _ = parse_claim_verification(
        '{"status":"CONTRADICTED","evidence_supported":"false","error_types":[]}',
        claim_id="claim-1",
    )

    assert evaluation.evidence_supported is False
