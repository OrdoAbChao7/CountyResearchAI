"""Tests for deterministic PDF extraction and ADR-005 read-only evidence adapter."""
from __future__ import annotations

import hashlib
import io
from datetime import date, datetime, timezone

import pytest

from county_research_ai.domain.research_contracts import (
    AtomicClaim,
    EvidenceChunk,
    ResearchContract,
    SourceDocument,
)
from county_research_ai.evidence.graph import (
    EvidenceGraphStore,
    FindingRecord,
)
from county_research_ai.evidence.ledger import EvidenceLedger
from county_research_ai.models import RawDoc
from county_research_ai.search.adaptive_retrieval import AdaptiveQueryPlan
from county_research_ai.search.base import SearchProvider
from county_research_ai.search.collector import SearchCollector
from county_research_ai.search.gov_data import GovDataProvider
from county_research_ai.search.pdf_extractor import (
    extract_pdf_text_bytes,
    is_pdf_document,
)
from county_research_ai.search.query_engine import GeneratedQuery, QueryIntent
from county_research_ai.search.request_history import (
    SearchRequestHistory,
    bind_search_history,
)
from county_research_ai.services.evidence_service import (
    EvidenceService,
    ReadOnlyEvidenceAdapterError,
)


def _make_ascii_pdf(text: str) -> bytes:
    """Create a minimal single-page valid PDF containing ``text`` using pypdf/raw PDF."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    page[NameObject("/Resources")] = resources
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    stream_ref = writer._add_object(stream)
    page[NameObject("/Contents")] = stream_ref

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfExtractor:
    def test_is_pdf_document_detects_url_and_mime(self):
        assert is_pdf_document("https://tjj.anji.gov.cn/art/2025/03/2024_tjgb.PDF?download=1")
        assert is_pdf_document("https://anji.gov.cn/download?id=9", "application/pdf; binary")
        assert not is_pdf_document("https://anji.gov.cn/tjgb/2024.html", "text/html")

    def test_extract_pdf_text_bytes_parses_stream_and_respects_max_chars(self):
        payload = _make_ascii_pdf("Deqing 2024 industrial output 722.5 billion")
        text, pages = extract_pdf_text_bytes(payload)
        assert pages == 1
        assert "Deqing 2024 industrial output 722.5 billion" in text

        truncated, _ = extract_pdf_text_bytes(payload, max_chars=20)
        assert len(truncated) == 20
        assert truncated.endswith("...")

    def test_extract_pdf_text_bytes_rejects_non_pdf(self):
        with pytest.raises(ValueError, match="not a valid PDF"):
            extract_pdf_text_bytes(b"<html>not a pdf</html>")

    def test_collector_fetches_and_parses_pdf_when_fetch_detail_enabled(
        self, tmp_settings, monkeypatch
    ):
        pdf_bytes = _make_ascii_pdf("Anji 2024 bamboo output 192 billion")

        class PdfLinkProvider(SearchProvider):
            name = "pdf-web"

            def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
                return [
                    RawDoc(
                        title="安吉县2024年统计公报附件",
                        url="https://tjj.anji.gov.cn/zfxxgk/2024_bulletin.pdf",
                        snippet="2024年公报PDF",
                        metadata={"content_type": "application/pdf"},
                    )
                ]

        monkeypatch.setattr(
            "county_research_ai.search.collector.fetch_pdf_bytes",
            lambda url, timeout=20.0: (pdf_bytes, "application/pdf"),
        )
        tmp_settings.search.fetch_detail = True
        contract = ResearchContract(
            objective="核验产值",
            regions=["安吉县"],
            required_questions=["2024年总产值是多少？"],
        )
        spec = contract.to_research_spec()
        collector = SearchCollector(web_provider=PdfLinkProvider(), settings=tmp_settings)
        history = SearchRequestHistory()
        query = GeneratedQuery(
            "安吉县 2024 统计公报", QueryIntent.ECONOMIC_SCALE, slot_id="contract:0"
        )

        with bind_search_history(history):
            result = collector.collect_adaptive(AdaptiveQueryPlan(spec, (query,)))

        assert len(result.documents) == 1
        assert "192 billion" in result.documents[0].content
        assert result.documents[0].metadata["pdf_parsed_by_app"] is True

        execution, = history.executions
        record, = execution.documents
        assert record.parse_status == "pdf_parsed"
        assert record.parse_reason == ""
        assert record.text_origin == "content"
        assert record.content_chars > 0

    def test_gov_provider_whitelist_and_pdf_detail_enrichment(
        self, tmp_settings, monkeypatch
    ):
        pdf_bytes = _make_ascii_pdf("Official statistical bulletin 2024")

        class GovPdfWeb(SearchProvider):
            name = "mock-web"

            def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
                return [
                    RawDoc(
                        title="德清县2024年国民经济和社会发展统计公报",
                        url="https://www.deqing.gov.cn/zfxxgk/gongbao/2024.pdf",
                        snippet="公报附件",
                    )
                ]

        class DummyResponse:
            status_code = 200
            headers = {"content-type": "application/pdf"}
            content = pdf_bytes
            text = ""

        class DummyClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url, headers=None):
                return DummyResponse()

        monkeypatch.setattr("county_research_ai.search.gov_data.httpx.Client", DummyClient)
        gov = GovDataProvider(web_provider=GovPdfWeb(), settings=tmp_settings, fetch_detail=True)
        docs = gov.search("德清县 统计公报", max_results=5)

        assert len(docs) == 1
        assert docs[0].source == "gov"
        assert "Official statistical bulletin 2024" in docs[0].content
        assert docs[0].metadata["pdf_parsed_by_app"] is True


def _build_source(
    doc_id: str,
    content: str,
    *,
    url: str,
    credibility: float = 0.9,
) -> SourceDocument:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunk = EvidenceChunk(
        chunk_id=f"{doc_id}:c1",
        document_id=doc_id,
        text=content,
        start_offset=0,
        end_offset=len(content),
        offset_status="exact",
        content_hash=digest,
    )
    return SourceDocument(
        doc_id=doc_id,
        canonical_url=url,
        source_title=f"来源-{doc_id}",
        content=content,
        content_hash=digest,
        provider="gov",
        source_type="government",
        fetch_status="fetched",
        retrieved_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        metadata={"credibility_score": credibility},
        chunks=[chunk],
    )


class TestVerifiedGraphEvidenceAdapter:
    def test_only_supported_in_window_target_region_findings_pass_through(self, tmp_path):
        src_ok = _build_source(
            "s-ok",
            "德清县2024年地理信息产业总产值为350亿元。",
            url="https://deqing.gov.cn/tjgb/2024",
            credibility=0.92,
        )
        src_weak = _build_source(
            "s-weak",
            "德清县2024年生物医药产值为120亿元。",
            url="https://blog.example.com/deqing",
            credibility=0.45,
        )
        src_old = _build_source(
            "s-old",
            "德清县2022年地理信息产业总产值为280亿元。",
            url="https://deqing.gov.cn/tjgb/2022",
            credibility=0.92,
        )
        src_other = _build_source(
            "s-other",
            "昆山市2024年电子信息产业总产值为7000亿元。",
            url="https://kunshan.gov.cn/tjgb/2024",
            credibility=0.95,
        )

        claims = [
            AtomicClaim(
                claim_id="c-supported",
                statement="德清县2024年地理信息产业总产值为350亿元",
                region_id="德清县",
                region_source="claim",
                metric_id="总产值",
                value="350",
                unit="亿元",
                period="2024",
                administrative_scope="县域本级",
                statistical_caliber="总产值",
                source_ids=["s-ok"],
                evidence_chunk_ids=["s-ok:c1"],
            ),
            AtomicClaim(
                claim_id="c-weak",
                statement="德清县2024年生物医药产值为120亿元",
                region_id="德清县",
                region_source="claim",
                metric_id="产值",
                value="120",
                unit="亿元",
                period="2024",
                source_ids=["s-weak"],
                evidence_chunk_ids=["s-weak:c1"],
            ),
            AtomicClaim(
                claim_id="c-out-of-window",
                statement="德清县2022年地理信息产业总产值为280亿元",
                region_id="德清县",
                region_source="claim",
                metric_id="总产值",
                value="280",
                unit="亿元",
                period="2022",
                source_ids=["s-old"],
                evidence_chunk_ids=["s-old:c1"],
            ),
            AtomicClaim(
                claim_id="c-other-region",
                statement="昆山市2024年电子信息产业总产值为7000亿元",
                region_id="昆山市",
                region_source="claim",
                metric_id="总产值",
                value="7000",
                unit="亿元",
                period="2024",
                source_ids=["s-other"],
                evidence_chunk_ids=["s-other:c1"],
            ),
        ]

        ledger = EvidenceLedger()
        for src in (src_ok, src_weak, src_old, src_other):
            ledger.add_source(src)
        for claim in claims:
            ledger.add_claim(claim)

        window = (date(2024, 1, 1), date(2024, 12, 31))
        graph = EvidenceGraphStore(tmp_path / "evidence.sqlite")
        graph.save_ledger(ledger, run_id="run-deqing", window=window, target_region="德清县")

        findings = []
        for claim in claims:
            chain = graph.get_chain(claim.claim_id, run_id="run-deqing")
            assert chain.verification is not None
            findings.append(
                FindingRecord(
                    finding_id=f"f:{claim.claim_id}",
                    run_id="run-deqing",
                    claim_id=claim.claim_id,
                    section="snapshot:economic_scale",
                    slot_ids=["contract:0"],
                    text=claim.statement,
                    status=chain.verification.status,
                )
            )
        graph.save_findings("run-deqing", findings)

        adapter = EvidenceService.from_verified_graph(
            graph,
            "run-deqing",
            window=window,
            target_region="德清县",
        )

        assert adapter.is_read_only is True
        items = adapter.all()
        assert [it.id for it in items] == ["c-supported"]
        item = items[0]
        assert item.verification_status == "SUPPORTED"
        assert item.year == "2024"
        assert item.region_id == "德清县"
        assert item.indicator_caliber == "总产值"
        assert item.credibility_score == pytest.approx(0.92)
        assert adapter.stats() == {
            "total": 1,
            "verified": 1,
            "unverified": 0,
            "conflicts": 0,
        }

        with pytest.raises(ReadOnlyEvidenceAdapterError):
            adapter.add(item)
        with pytest.raises(ReadOnlyEvidenceAdapterError):
            adapter.ingest([], county="德清县")
