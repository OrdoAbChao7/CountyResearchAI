from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from county_research_ai.api.projections import (
    build_evidence_list,
    build_graph_view,
    build_questions_view,
    build_report_view,
)
from county_research_ai.api.projections.report import split_markdown_sections
from county_research_ai.evidence.graph import VerificationStatus
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


def test_fact_citation_uses_the_span_that_supports_the_claim(tmp_path):
    support = "安吉县2024年竹产业产值为120亿元。"
    source = make_source(
        "snap-multiple", url="https://example.gov.cn/multiple",
        content="安吉县持续完善竹林资源监测。", extra_chunks=(support,),
    )
    claim = make_claim(
        "claim-multiple", source_id=source.doc_id,
        chunk_ids=[chunk.chunk_id for chunk in source.chunks],
    )
    graph = seed_graph(tmp_path / "graph.sqlite", RUN_ID, sources=[source], claims=[claim])
    job = make_job(result=deep_result())

    view = build_report_view(job=job, graph=graph)

    assert view.citations[0].quote == support
    assert view.citations[0].snapshot_id == "snap-multiple"
    assert view.citations[0].span_id == "snap-multiple:chunk:2"
    assert support in view.sections[1].content
    assert source.chunks[0].text not in view.sections[1].content
    evidence = build_evidence_list(job=job, graph=graph).items[0]
    assert evidence.citation_number == view.citations[0].n
    assert evidence.links[0].span_id == view.citations[0].span_id


def test_a_candidate_cites_the_matching_quote_even_if_the_first_span_does_not_match(tmp_path):
    quote = "安吉县2024年竹产业产值为120亿元。"
    source = make_source(
        "snap-multiple", url="https://example.com/bamboo", content="安吉县持续完善竹林资源监测。", extra_chunks=(quote,),
    ).model_copy(update={"metadata": {"credibility_score": 0.5}})
    claim = make_claim("claim-multiple", source_id=source.doc_id, chunk_ids=[chunk.chunk_id for chunk in source.chunks])
    graph = seed_graph(tmp_path / "graph.sqlite", RUN_ID, sources=[source], claims=[claim])

    view = build_report_view(job=make_job(result=deep_result()), graph=graph)

    assert view.verification.verified == 0
    citation, = view.citations
    assert citation.status == "INSUFFICIENT" and citation.quote == quote
    assert citation.span_id == "snap-multiple:chunk:2"


@pytest.mark.parametrize("shared_url", [False, True], ids=["separate-sources", "same-url-new-snapshot"])
def test_legacy_dispute_is_reassessed_without_overwriting_archived_records(tmp_path, shared_url):
    strong = make_source(
        "strong", url="https://example.gov.cn/stats", content="安吉县2024年竹产业总产值为120亿元。",
    ).model_copy(update={"metadata": {"credibility_score": 0.9}})
    weak = make_source(
        "weak", url=strong.canonical_url if shared_url else "https://example.com/bamboo",
        content="安吉县2024年竹产业总产值为130亿元。",
    ).model_copy(update={"metadata": {"credibility_score": 0.5}})
    claims = [
        make_claim("claim-strong", source_id=strong.doc_id, metric="竹产业总产值"),
        make_claim("claim-weak", source_id=weak.doc_id, metric="竹产业总产值", value="130"),
    ]
    graph = seed_graph(tmp_path / "graph.sqlite", RUN_ID, sources=[strong, weak], claims=claims,
                       statuses={claim.claim_id: VerificationStatus.NEEDS_REVIEW for claim in claims})
    with closing(sqlite3.connect(graph.path)) as connection, connection:
        connection.execute("UPDATE verification_records SET status = 'NEEDS_REVIEW', verifier_version = 'deterministic_v2_local_binding'")
    legacy_conflict = {"indicator": "竹产业总产值", "conflict_type": "contradiction", "claims": [
        {"value": "120亿元", "year": "2024", "url": strong.canonical_url},
        {"value": "130亿元", "year": "2024", "url": weak.canonical_url},
    ]}
    job = make_job(result=deep_result(conflicts=[legacy_conflict]))
    job.contract = job.contract.model_copy(update={"required_questions": ["2024年安吉县竹产业总产值是多少？"]})

    view = build_report_view(job=job, graph=graph)

    assert not view.conflicts and not view.claim_conflicts
    assert not build_questions_view(job, graph=graph).conflicts
    graph_view = build_graph_view(job=job, graph=graph)
    assert not [node for node in graph_view.nodes if node.type == "conflict"]
    assert not [edge for edge in graph_view.edges if edge.type == "conflicts_with"]
    assert job.result["deep_research"]["conflicts"] == [legacy_conflict]
    assert view.sections[1].citation_ids == ["claim-strong"]
    question, = view.contract_questions
    assert (question.status, question.claim_ids) == ("SUPPORTED", ["claim-strong"])
    assert graph.get_chain("claim-strong", run_id=RUN_ID).verification.status is VerificationStatus.NEEDS_REVIEW


@pytest.mark.parametrize("column,value", [("start_offset", 1), ("content_hash", "wrong")])
def test_broken_reference_cannot_remain_a_verified_fact(tmp_path, column, value):
    graph, supported, _ = _report_graph(tmp_path)
    with closing(sqlite3.connect(graph.path)) as connection, connection:
        connection.execute(
            f"UPDATE evidence_spans SET {column} = ? WHERE span_id = ?",
            (value, "snap-supported:chunk:1"),
        )
    job = make_job(result=deep_result())

    view = build_report_view(job=job, graph=graph)

    assert view.verification.verified == 0
    assert supported.claim_id not in view.sections[1].citation_ids
    assert supported.claim_id not in {cite.claim_id for cite in view.citations}
    item = next(item for item in build_evidence_list(job=job, graph=graph).items
                if item.claim_id == supported.claim_id)
    assert item.status == "INSUFFICIENT"
    assert item.reason == "false_or_broken_reference"


def test_split_markdown_sections_skips_title_only_preamble():
    sections = split_markdown_sections("# 标题\n\n## 第一节\n\n内容\n")

    assert [section.title for section in sections] == ["第一节"]
    assert sections[0].content == "内容"


def test_report_escapes_malicious_source_text_without_dropping_facts(tmp_path):
    source = make_source(
        "snap-malicious",
        url="javascript:alert(1)",
        title="<img src=x onerror=alert(1)>",
        content="安吉县2024年竹产业产值为120亿元。<script>alert(1)</script>",
    )
    claim = make_claim(
        "claim-malicious",
        source_id="snap-malicious",
        value="120",
        unit="亿元",
        period="2024",
        metric="竹产业产值",
        statement="安吉县2024年竹产业产值为120亿元 <script>alert(1)</script>",
    )
    graph = seed_graph(
        tmp_path / "graph.sqlite",
        RUN_ID,
        sources=[source],
        claims=[claim],
    )

    view = build_report_view(job=make_job(result=deep_result()), graph=graph)

    assert view.verification.verified == 1
    verified = next(
        section for section in view.sections if section.id == "verified-facts"
    )
    assert "120亿元" in verified.content
    assert "2024" in verified.content
    assert "竹产业产值" in verified.content
    assert view.citations[0].value == "120"
    assert view.citations[0].unit == "亿元"
    assert view.citations[0].period == "2024"

    assert "<script>" not in view.markdown
    assert "<img" not in view.markdown
    assert "](javascript:" not in view.markdown
    assert "&lt;script&gt;" in view.markdown
