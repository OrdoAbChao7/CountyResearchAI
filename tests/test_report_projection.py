from __future__ import annotations

from county_research_ai.api.projections import build_report_view
from county_research_ai.api.projections.report import split_markdown_sections
from tests.projection_helpers import (
    RUN_ID,
    deep_result,
    make_claim,
    make_job,
    make_source,
    seed_graph,
)


def _report_graph(tmp_path):
    supported_source = make_source(
        "snap-supported",
        url="https://example.gov.cn/supported",
        content="安吉县2024年竹产业产值为120亿元。",
    )
    missing_source = make_source(
        "snap-missing",
        url="https://example.gov.cn/missing",
        content="安吉县2024年竹林面积为80万亩。",
    )
    supported = make_claim(
        "claim-supported",
        source_id="snap-supported",
        value="120",
        metric="竹产业产值",
    )
    missing = make_claim(
        "claim-missing",
        source_id="snap-missing",
        value="999",
        metric="竹加工产值",
        statement="安吉县2024年竹加工产值为999亿元",
    )
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[supported_source, missing_source],
        claims=[supported, missing],
    )
    return graph, supported, missing


def test_verified_report_uses_only_supported_facts(tmp_path):
    graph, supported, missing = _report_graph(tmp_path)
    gaps = [
        {
            "question_id": "q-output",
            "missing_aspect": "竹加工产值",
            "description": "缺少竹加工产值的直接来源",
            "severity": "high",
        }
    ]
    conflicts = [
        {
            "indicator": "竹产业产值",
            "conflict_type": "value_discrepancy",
            "description": "来源 A 与来源 B 的产值不一致",
            "resolution_suggestion": "回查统计公报原文",
        }
    ]
    job = make_job(result=deep_result(gaps=gaps, conflicts=conflicts))

    view = build_report_view(job=job, graph=graph)

    assert view.provenance == "verified_structured_facts"
    assert [section.id for section in view.sections] == [
        "summary",
        "verified-facts",
        "disputes",
        "gaps",
        "sources",
        "method",
    ]
    verified = next(
        section for section in view.sections if section.id == "verified-facts"
    )
    assert supported.statement in verified.content
    assert "120亿元" in verified.content
    assert missing.statement not in verified.content
    assert "999" not in verified.content
    assert supported.claim_id in verified.citation_ids
    assert missing.claim_id not in verified.citation_ids

    assert missing.statement not in view.markdown
    assert "999" not in view.markdown
    assert "缺少竹加工产值的直接来源" in view.markdown
    assert "来源 A 与来源 B 的产值不一致" in view.markdown
    assert view.verification.verified == 1
    assert view.verification.unverified == 1
    assert view.verification.total == 2
    assert view.citations[0].n == 1
    assert view.citations[0].claim_id == supported.claim_id
    assert view.citations[0].value == "120"
    assert view.citations[0].unit == "亿元"
    assert view.citations[0].period == "2024"
    assert view.markdown.startswith("# 安吉县竹产业研究报告")


def test_report_splits_rise_fall_markdown_and_marks_provenance(tmp_path):
    graph, _, _ = _report_graph(tmp_path)
    legacy = (
        "# 安吉县竹产业旧版分析\n\n"
        "这是一段总体背景。\n\n"
        "## 产业概况\n\n"
        "旧版叙述中的产业概况。\n\n"
        "## 财政表现\n\n"
        "旧版叙述中的财政表现。\n"
    )
    job = make_job(result={}, mode="rise_fall")

    view = build_report_view(job=job, graph=graph, legacy_markdown=legacy)

    assert view.narrative.provenance == "markdown_split"
    assert [section.title for section in view.narrative.sections] == [
        "全文",
        "产业概况",
        "财政表现",
    ]
    assert view.narrative.sections[0].content == "这是一段总体背景。"
    assert view.narrative.sections[1].content == "旧版叙述中的产业概况。"
    assert view.narrative.markdown_available is True
    assert not [section for section in view.sections if section.id.startswith("narrative")]


def test_report_uses_snapshot_native_sections_when_available(tmp_path):
    graph, _, _ = _report_graph(tmp_path)
    result = deep_result()
    result["report"] = {
        "provenance": "native_sections",
        "sections": [
            {
                "title": "研究背景",
                "order": 1,
                "content": "安吉县竹产业进入集群发展阶段。",
                "sources": ["https://example.gov.cn/context"],
            },
            {
                "title": "产业现状",
                "order": 2,
                "content": "竹产业产值达到 120 亿元。",
                "sources": [],
            },
        ],
    }
    job = make_job(result=result, mode="snapshot")

    view = build_report_view(job=job, graph=graph, legacy_markdown="# 旧稿\n正文")

    assert view.narrative.provenance == "native_sections"
    assert [section.title for section in view.narrative.sections] == [
        "研究背景",
        "产业现状",
    ]
    assert view.narrative.sections[0].sources == ["https://example.gov.cn/context"]
    assert view.narrative.sections[1].order == 2


def test_report_is_honest_when_no_claim_is_supported(tmp_path):
    source = make_source(
        "snap-none",
        url="https://example.gov.cn/none",
        content="安吉县2024年竹林面积为80万亩。",
    )
    claim = make_claim(
        "claim-none",
        source_id="snap-none",
        value="999",
        metric="竹加工产值",
        statement="安吉县2024年竹加工产值为999亿元",
    )
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[source],
        claims=[claim],
    )
    job = make_job(result=deep_result())

    view = build_report_view(job=job, graph=graph)

    verified = next(
        section for section in view.sections if section.id == "verified-facts"
    )
    assert "没有通过确定性校验" in verified.content
    assert view.verification.verified == 0
    assert view.verification.unverified == 1
    assert "999" not in view.markdown
    assert claim.statement not in view.markdown


def test_split_markdown_sections_skips_title_only_preamble():
    sections = split_markdown_sections("# 标题\n\n## 第一节\n\n内容\n")

    assert [section.title for section in sections] == ["第一节"]
    assert sections[0].content == "内容"
