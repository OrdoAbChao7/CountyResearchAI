from __future__ import annotations

from scripts.q7_retrieve_missing import _metric_aliases, _queries, score_page

from county_research_ai.evaluation.ground_truth import GroundTruthClaim


def _claim(**overrides) -> GroundTruthClaim:
    values = {
        "claim_id": "q7-claim",
        "claim": "2006年规模企业产值完成289亿元",
        "source": "德清县2007年政府工作报告",
        "url": "http://example.gov.cn/report",
        "date": "2007-03-13",
        "region": "德清县",
        "metric": "规模企业产值",
        "unit": "亿元",
        "evidence_excerpt": "规模企业产值完成289亿元",
        "confidence": "high",
        "verification_status": "VERIFIED",
        "expected_answer": "2006年德清县规模企业产值289亿元",
        "metric_year": "2006",
    }
    values.update(overrides)
    return GroundTruthClaim(**values)


def test_query_plan_uses_region_metric_year_without_gt_url():
    queries = _queries(_claim())

    assert any("德清县" in query and "规模企业产值" in query and "2006" in query for query in queries)
    assert any("政府工作报告" in query for query in queries)
    assert all("example.gov.cn" not in query for query in queries)


def test_metric_aliases_cover_scale_and_suffix_variants():
    aliases = _metric_aliases(_claim(metric="规模以上企业数量"))

    assert any("规模以上工业企业" in alias for alias in aliases)
    assert any(alias == "规模以上企业" for alias in aliases)


def test_exact_excerpt_and_alias_value_metric_recovery():
    claim = _claim()
    exact = score_page(
        claim,
        "2006年规模企业产值完成289亿元。",
        "德清县2007年政府工作报告",
        "http://example.gov.cn/report",
    )
    alias = score_page(
        claim,
        "全县规模以上工业总产值289.0亿元，比上年增长30.1%。",
        "德清县统计局2006年统计公报",
        "http://example.gov.cn/bulletin",
    )

    assert exact["hit"] is True
    assert exact["recovery_mode"] == "exact_excerpt"
    assert alias["hit"] is True
    assert alias["recovery_mode"] == "value_metric"


def test_wrong_region_or_year_does_not_recover():
    claim = _claim()
    wrong_region = score_page(
        claim,
        "长兴县规模以上工业总产值289.0亿元。",
        "长兴县统计公报",
        "http://example.gov.cn/cx",
    )
    wrong_year = score_page(
        claim,
        "2005年规模以上工业总产值289.0亿元。",
        "2005年德清县统计公报",
        "http://example.gov.cn/2005",
    )

    assert wrong_region["hit"] is False
    assert wrong_year["hit"] is False
