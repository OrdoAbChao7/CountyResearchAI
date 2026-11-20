from __future__ import annotations

import json
from pathlib import Path

import pytest

from county_research_ai.evaluation.claim_verification import (
    build_claim_verification_prompt,
    deterministic_claim_check,
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


def test_claim_verification_prompt_includes_rich_scope_and_expected_answer():
    claim = GroundTruthClaim(
        **{
            **_claim().__dict__,
            "metric": "产业产值",
            "research_mode": "snapshot",
            "expected_answer": "2024年县域本级产业产值为10亿元",
            "source_title": "2024年统计公报",
            "source_date": "2025-03-01",
            "metric_year": "2024",
            "administrative_scope": "县域本级",
            "verification_sources": ("source-a", "source-b"),
            "verification_contexts": ("context-a", "context-b"),
        }
    )

    prompt = build_claim_verification_prompt(
        report="报告",
        source_material="来源",
        claim=claim,
    )

    assert "expected_answer=2024年县域本级产业产值为10亿元" in prompt
    assert "administrative_scope=县域本级" in prompt


def test_deterministic_claim_check_covers_calibration_statuses():
    claim = GroundTruthClaim(
        **{
            **_claim().__dict__,
            "metric": "产业产值",
            "research_mode": "snapshot",
            "expected_answer": "2024年县域本级产业产值为10亿元",
            "source_title": "2024年统计公报",
            "source_date": "2025-03-01",
            "metric_year": "2024",
            "administrative_scope": "县域本级",
            "verification_sources": ("source-a", "source-b"),
            "verification_contexts": ("context-a", "context-b"),
        }
    )
    cases = {
        "supported": (
            "2024年县域本级产业产值为10亿元。",
            "2024年统计公报：县域本级产业产值为10亿元。",
            ClaimStatus.SUPPORTED,
        ),
        "contradicted": (
            "2024年县域本级产业产值为12亿元。",
            "2024年统计公报：县域本级产业产值为10亿元。",
            ClaimStatus.CONTRADICTED,
        ),
        "unsupported": (
            "2024年县域本级产业情况需要进一步调研。",
            "来源只讨论人口规模，没有产业产值数据。",
            ClaimStatus.UNSUPPORTED,
        ),
        "missing": (
            "报告仅讨论交通条件。",
            "来源仅讨论交通条件。",
            ClaimStatus.UNVERIFIED,
        ),
        "disputed": (
            "2024年县域本级产业产值为10亿元。",
            "两份来源对县域本级产业产值的统计口径存在争议。",
            ClaimStatus.DISPUTED,
        ),
        "scope_confused": (
            "2024年全市产业产值为10亿元。",
            "2024年统计公报：县域本级产业产值为10亿元。",
            ClaimStatus.CONTRADICTED,
        ),
    }

    for name, (report, source_material, expected_status) in cases.items():
        result = deterministic_claim_check(
            report=report,
            source_material=source_material,
            claim=claim,
        )
        assert result is not None, name
        assert result.evaluation.status is expected_status, name

    contradicted = deterministic_claim_check(
        report=cases["scope_confused"][0],
        source_material=cases["scope_confused"][1],
        claim=claim,
    )
    assert contradicted is not None
    assert "scope_mismatch" in contradicted.evaluation.error_types


def test_deterministic_claim_check_accepts_county_level_scope_synonyms():
    claim = GroundTruthClaim(
        **{
            **_claim().__dict__,
            "expected_answer": "2024年新地区县本级地区生产总值为10亿元",
            "metric_year": "2024",
            "administrative_scope": "新地区县本级",
            "verification_sources": ("source-a", "source-b"),
            "verification_contexts": ("context-a", "context-b"),
        }
    )

    result = deterministic_claim_check(
        report="2024年全县实现地区生产总值10亿元。",
        source_material="2024年统计公报：全县地区生产总值为10亿元。",
        claim=claim,
    )

    assert result is not None
    assert result.evaluation.status is ClaimStatus.SUPPORTED


def test_deterministic_claim_check_accepts_percent_unit_alias():
    claim = GroundTruthClaim(
        **{
            **_claim().__dict__,
            "metric": "产业增长率",
            "unit": "百分比",
            "expected_answer": "2024年新地区县本级产业增长率为5.8%",
            "metric_year": "2024",
            "administrative_scope": "新地区县本级",
            "verification_sources": ("source-a", "source-b"),
            "verification_contexts": ("context-a", "context-b"),
        }
    )

    result = deterministic_claim_check(
        report="2024年全县产业增长率为5.8%。",
        source_material="2024年统计公报：全县产业增长率为5.8%。",
        claim=claim,
    )

    assert result is not None
    assert result.evaluation.status is ClaimStatus.SUPPORTED


def test_offline_judge_calibration_fixture_has_no_provider_dependency():
    fixture = (
        Path(__file__).parents[1]
        / "experiments"
        / "independent_comparison"
        / "fixtures"
        / "judge_calibration_cases.jsonl"
    )
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]

    assert {row["case_id"] for row in rows} == {
        "supported",
        "contradicted",
        "unsupported",
        "missing",
        "disputed",
        "scope_confused",
    }
    for row in rows:
        claim = GroundTruthClaim.from_dict(row["claim"])
        result = deterministic_claim_check(
            report=row["report"],
            source_material=row["source_material"],
            claim=claim,
        )
        assert result is not None
        assert result.evaluation.status.value == row["expected_status"]


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
