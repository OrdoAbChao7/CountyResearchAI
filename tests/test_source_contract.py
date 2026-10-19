from __future__ import annotations

from datetime import datetime, timezone

from county_research_ai.evidence.source_contract import serialize_source_documents
from county_research_ai.models import RawDoc


def test_source_contract_is_deterministic_and_maps_chunk_offsets():
    content = "统计正文" * 250
    document = RawDoc(
        title="官方统计公报",
        url="https://example.gov.cn/bulletin",
        content=content,
        source="tavily",
        domain_type="government",
        published_at=datetime(2025, 3, 31, tzinfo=timezone.utc),
    )

    first = serialize_source_documents([document])[0]
    second = serialize_source_documents([document])[0]

    assert first == second
    assert first["provider"] == "tavily"
    assert first["source_type"] == "government"
    assert first["document_timestamp"] == "2025-03-31T00:00:00+00:00"
    assert first["fetch_status"] == "fetched"
    assert first["chunks"]
    assert first["chunks"][0]["start_offset"] == 0
    assert first["chunks"][-1]["end_offset"] == len(content)
    assert all(chunk["text"] for chunk in first["chunks"])


def test_source_contract_distinguishes_snippet_only_from_fetched_content():
    document = RawDoc(
        title="搜索摘要",
        url="https://example.gov.cn/search",
        snippet="摘要中的统计线索",
        source="tavily",
    )

    record = serialize_source_documents([document])[0]

    assert record["fetch_status"] == "snippet_only"
    assert record["content"] == "摘要中的统计线索"
    assert record["chunks"]


def test_source_contract_preserves_truncation_audit_fields():
    document = RawDoc(
        title="截断统计公报",
        url="https://example.gov.cn/truncated",
        content="保留的正文",
        content_original_length=1000,
        content_truncated=True,
        truncation_reason="max_evidence_length:10",
    )

    record = serialize_source_documents([document])[0]

    assert record["content_original_length"] == 1000
    assert record["content_truncated"] is True
    assert record["truncation_reason"] == "max_evidence_length:10"
