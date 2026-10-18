from __future__ import annotations

import pytest
from scripts.collect_continuation_ground_truth import _claims_per_region_task

from county_research_ai.evaluation.ground_truth import GroundTruthClaim
from county_research_ai.evaluation.ground_truth_collection import (
    build_query_plan,
    claims_from_extraction,
    parse_extraction_response,
)


def test_manifest_region_task_keys_are_json_serializable():
    claim = GroundTruthClaim(
        claim_id="c1",
        claim="事实",
        source="来源",
        url="https://a.gov.cn",
        date="2025",
        region="示例县",
        metric="指标",
        unit="单位",
        evidence_excerpt="事实",
        confidence="high",
        verification_status="VERIFIED",
        verification_sources=("https://a.gov.cn", "https://b.gov.cn"),
        verification_contexts=("ctx-a", "ctx-b"),
        research_mode="snapshot",
        expected_answer="事实",
        source_title="来源",
        source_date="2025",
        metric_year="2024",
        administrative_scope="县域本级",
    )

    assert _claims_per_region_task([claim]) == {"示例县::snapshot": 1}


def test_query_plan_has_two_named_independent_contexts():
    plan = build_query_plan(
        region_id="region_01",
        region="德清县",
        province="浙江省",
        mode="snapshot",
    )

    assert len(plan) == 2
    assert {item["context_id"] for item in plan} == {
        "region_01_snapshot_official_bulletin",
        "region_01_snapshot_official_yearbook",
    }
    assert all("德清县" in item["query"] for item in plan)


def test_rise_fall_second_context_targets_independent_official_statistics():
    plan = build_query_plan(
        region_id="region_01",
        region="德清县",
        province="浙江省",
        mode="rise-fall",
    )

    assert plan[1]["context_id"] == "region_01_rise-fall_official_comparison"
    assert "主要经济指标" in plan[1]["query"]


def test_parse_extraction_response_accepts_json_fence():
    content = '```json\n{"claims": [{"claim": "x"}]}\n```'

    assert parse_extraction_response(content) == {"claims": [{"claim": "x"}]}


def test_claims_from_extraction_requires_verbatim_evidence_and_two_contexts():
    response = {
        "claims": [
            {
                "claim": "2024年GDP为10亿元。",
                "metric": "地区生产总值",
                "unit": "亿元",
                "expected_answer": "2024年县域本级GDP为10亿元。",
                "metric_year": "2024",
                "administrative_scope": "县域本级",
                "source_title": "2024年统计公报",
                "source_date": "2025-03-01",
                "primary_context_id": "ctx-a",
                "primary_url": "https://a.gov.cn/bulletin",
                "evidence_excerpt": "2024年GDP为10亿元。",
                "verification_urls": ["https://b.gov.cn/yearbook"],
                "verification_evidence": [
                    {
                        "url": "https://b.gov.cn/yearbook",
                        "excerpt": "年鉴记载2024年GDP为10亿元。",
                    }
                ],
                "verification_context_ids": ["ctx-b"],
                "confidence": "high",
            }
        ]
    }
    evidence = {
        "https://a.gov.cn/bulletin": {
            "title": "2024年统计公报",
            "text": "2024年GDP为10亿元。",
        },
        "https://b.gov.cn/yearbook": {
            "title": "2025年统计年鉴",
            "text": "年鉴记载2024年GDP为10亿元。",
        },
    }

    claims = claims_from_extraction(
        response,
        region="示例县",
        mode="snapshot",
        evidence=evidence,
        known_contexts={"ctx-a", "ctx-b"},
    )

    assert claims[0].verification_status == "VERIFIED"
    assert claims[0].verification_sources == tuple(evidence)
    assert claims[0].verification_contexts == ("ctx-a", "ctx-b")
    assert claims[0].verification_excerpts == (
        "2024年GDP为10亿元。",
        "年鉴记载2024年GDP为10亿元。",
    )


def test_claims_from_extraction_rejects_non_verbatim_excerpt():
    response = {
        "claims": [
            {
                "claim": "事实",
                "metric": "指标",
                "unit": "单位",
                "expected_answer": "事实",
                "metric_year": "2024",
                "administrative_scope": "县域本级",
                "source_title": "来源",
                "source_date": "2025-03-01",
                "primary_context_id": "ctx-a",
                "primary_url": "https://a.gov.cn/bulletin",
                "evidence_excerpt": "模型编造的摘录",
                "verification_urls": ["https://b.gov.cn/yearbook"],
                "verification_evidence": [
                    {"url": "https://b.gov.cn/yearbook", "excerpt": "原文"}
                ],
                "verification_context_ids": ["ctx-b"],
                "confidence": "high",
            }
        ]
    }
    evidence = {
        "https://a.gov.cn/bulletin": {"title": "来源", "text": "官方原文"},
        "https://b.gov.cn/yearbook": {"title": "年鉴", "text": "原文"},
    }

    with pytest.raises(ValueError, match="verbatim"):
        claims_from_extraction(
            response,
            region="示例县",
            mode="snapshot",
            evidence=evidence,
            known_contexts={"ctx-a", "ctx-b"},
        )
