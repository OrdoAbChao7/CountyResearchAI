"""V2 服务层测试：证据、定量、报告、缺口雷达、数字孪生、时序。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from county_research_ai.domain.intelligence import (
    GapType,
    IntelligenceReport,
    OpportunityCandidate,
    ReportSectionV2,
    VerificationStatus,
)
from county_research_ai.knowledge_graph.graph_store.mock_store import InMemoryGraphStore
from county_research_ai.knowledge_graph.ontology.entities import EntityType, KGEntity
from county_research_ai.knowledge_graph.ontology.relations import KGRelation, RelationshipType
from county_research_ai.knowledge_graph.temporal.models import TemporalQuery
from county_research_ai.services.evidence_service import EvidenceService
from county_research_ai.services.opportunity_service import GapRadarService
from county_research_ai.services.quant_service import QuantService
from county_research_ai.shining_stars.digital_twin import (
    BaselineProfile,
    DigitalTwinService,
    ScenarioShock,
    SimulationEngineUnavailable,
    SimulationRequest,
    SimulationScenario,
)


class TestQuantService:
    def test_location_quotient(self):
        result = QuantService.location_quotient(20, 100, 100, 1000)
        assert result.value == pytest.approx(2.0)
        assert "专业化" in result.interpretation

    def test_location_quotient_rejects_zero_denominator(self):
        with pytest.raises(ValueError):
            QuantService.location_quotient(10, 0, 10, 100)

    def test_shift_share_sums_to_total_change(self):
        result = QuantService.shift_share(
            100,
            130,
            1000,
            1100,
            reference_industry_start=200,
            reference_industry_end=240,
        )
        total = (
            result["regional_share"]
            + result["structural_share"]
            + result["competitive_share"]
        )
        assert total == pytest.approx(30, abs=1e-4)
        assert result["industry_growth_source"] == "reference_industry"

    def test_shift_share_marks_proxy_when_industry_data_missing(self):
        result = QuantService.shift_share(100, 130, 1000, 1100)
        assert result["industry_growth_source"] == "reference_total_proxy"
        assert "代理" in result["interpretation"]

    def test_hhi(self):
        result = QuantService.hhi([50, 50])
        assert result.value == pytest.approx(0.5)
        assert "集中" in result.interpretation

    def test_hhi_normalized(self):
        result = QuantService.hhi([80, 10, 10], normalize=True)
        assert 0 <= result.value <= 1
        assert result.value < QuantService.hhi([80, 10, 10]).value

    def test_cr_n(self):
        result = QuantService.cr_n([10, 30, 60], n=2)
        assert result.value == pytest.approx(0.9)

    def test_cagr(self):
        result = QuantService.cagr(100, 121, 2)
        assert result.value == pytest.approx(0.1, abs=1e-6)


class TestEvidenceService:
    def test_ingest_search_and_persist(self, tmp_path, sample_docs):
        service = EvidenceService()
        items = service.ingest(sample_docs, county="安吉县", focus="竹产业")
        assert items
        assert service.get(items[0].id) is not None
        hits = service.search(["产值"])
        assert hits
        path = service.persist(tmp_path / "evidence.json")
        assert path.exists()

        restored = EvidenceService()
        count = restored.load(path)
        assert count == len(service.all())
        assert restored.get(items[0].id) is not None

    def test_render_for_prompt_contains_ids(self, sample_docs):
        service = EvidenceService()
        items = service.ingest(sample_docs, county="安吉县", focus="竹产业")
        text = service.render_for_prompt(limit=5)
        assert items[0].id in text

    def test_unknown_evidence_id_is_none(self):
        assert EvidenceService().get("missing") is None


class TestReportService:
    def test_render_platform_report(self, tmp_path, tmp_settings):
        from county_research_ai.services.report_service import ReportService
        from county_research_ai.storage.local_fs import LocalFSStorage

        service = ReportService(LocalFSStorage(settings=tmp_settings))
        report = IntelligenceReport(
            run_id="run-x",
            county="安吉县",
            focus="竹产业",
            research_question="安吉县竹产业如何补链？",
            executive_summary="结论摘要",
            sections=[
                ReportSectionV2(title="产业基础", content="竹产业产值120亿元", order=0)
            ],
            opportunities=[
                OpportunityCandidate(
                    title="补链",
                    gap_type=GapType.MISSING_SEGMENT,
                    segment="下游销售",
                    score=0.8,
                    evidence_ids=["ev-1"],
                )
            ],
            gaps=["缺少企业级数据"],
        )
        markdown = service.render_platform(report)
        assert "结论摘要" in markdown
        assert "产业基础" in markdown
        assert "补链" in markdown
        assert "缺少企业级数据" in markdown


def _seed_gap_graph() -> InMemoryGraphStore:
    graph = InMemoryGraphStore()

    def entity(kind: EntityType, name: str, *, county: str = "", ev: str = "ev-1") -> KGEntity:
        return KGEntity(
            type=kind,
            name=name,
            county=county,
            evidence_ids=[ev],
            confidence=0.9,
            verification_status=VerificationStatus.VERIFIED,
        )

    county = entity(EntityType.COUNTY, "安吉县", ev="ev-county")
    industry = entity(EntityType.INDUSTRY, "竹产业", county="安吉县", ev="ev-industry")
    upstream = entity(EntityType.INDUSTRY_SEGMENT, "上游种植", ev="ev-segment")
    midstream = entity(EntityType.INDUSTRY_SEGMENT, "中游加工", ev="ev-segment")
    downstream = entity(EntityType.INDUSTRY_SEGMENT, "下游销售", ev="ev-segment")
    enterprise = entity(
        EntityType.ENTERPRISE, "安吉竹业股份有限公司", county="安吉县", ev="ev-enterprise"
    )
    external = entity(EntityType.ENTERPRISE, "江苏竹机有限公司", county="常州市", ev="ev-external")
    for item in (county, industry, upstream, midstream, downstream, enterprise, external):
        graph.upsert_entity(item)

    def relate(source, target, kind, ev):
        graph.upsert_relation(
            KGRelation(
                source_entity_id=source.id,
                target_entity_id=target.id,
                relationship_type=kind,
                source_evidence_id=ev,
                confidence=0.9,
                verification_status=VerificationStatus.VERIFIED,
            )
        )

    relate(county, industry, RelationshipType.HAS_INDUSTRY, "ev-county")
    relate(industry, upstream, RelationshipType.CONTAINS, "ev-segment")
    relate(industry, midstream, RelationshipType.CONTAINS, "ev-segment")
    relate(industry, downstream, RelationshipType.CONTAINS, "ev-segment")
    relate(enterprise, midstream, RelationshipType.BELONGS_TO, "ev-enterprise")
    relate(enterprise, external, RelationshipType.USES_INPUT, "ev-external")
    return graph


class TestGapRadar:
    def test_detects_missing_weak_and_external(self):
        radar = GapRadarService(_seed_gap_graph())
        report = radar.scan("安吉县", "竹产业")
        assert set(report.missing_segments) == {"上游种植", "下游销售"}
        assert report.weak_segments == ["中游加工"]
        assert "江苏竹机有限公司" in report.external_dependencies
        kinds = {op.gap_type for op in report.opportunities}
        assert GapType.MISSING_SEGMENT in kinds
        assert GapType.WEAK_LOCAL_SUPPLY in kinds
        assert GapType.EXTERNAL_DEPENDENCY in kinds
        assert all(op.verification_status != VerificationStatus.VERIFIED for op in report.opportunities)

    def test_empty_graph_is_degraded(self):
        report = GapRadarService(InMemoryGraphStore()).scan("安吉县", "竹产业")
        assert report.degraded is True
        assert report.opportunities == []

    def test_location_quotient_opportunity(self):
        radar = GapRadarService(_seed_gap_graph())
        report = radar.scan(
            "安吉县",
            "竹产业",
            lq_inputs={
                "local_industry": 10,
                "local_total": 100,
                "reference_industry": 100,
                "reference_total": 1000,
            },
        )
        # LQ=1.0，不应产生低专业化机会
        assert report.specialization_score == pytest.approx(1.0)
        assert all(op.gap_type != GapType.LOW_SPECIALIZATION for op in report.opportunities)


class TestDigitalTwin:
    def _request(self, **shocks) -> SimulationRequest:
        return SimulationRequest(
            baseline=BaselineProfile(
                county="安吉县",
                industry="竹产业",
                output_yi=100,
                growth_rate=0.1,
                employment=10000,
                enterprise_count=80,
                source_year=2025,
                evidence_ids=["ev-1"],
                verification_status=VerificationStatus.VERIFIED,
            ),
            scenario=SimulationScenario(
                name="test", horizon_years=2, shocks=ScenarioShock(**shocks)
            ),
        )

    def test_baseline_projection(self):
        service = DigitalTwinService()
        outcome = service.simulate(self._request())
        assert outcome.projections[2].output_yi == pytest.approx(121)
        assert outcome.verification_status == VerificationStatus.INFERRED
        assert any(a.key == "no_price_or_policy_feedback" for a in outcome.assumptions)

    def test_investment_shock(self):
        service = DigitalTwinService()
        outcome = service.simulate(self._request(investment_yi=10))
        assert outcome.projections[1].output_yi == pytest.approx(120)
        assert outcome.projections[2].output_yi == pytest.approx(142)

    def test_missing_evidence_is_degraded(self):
        service = DigitalTwinService()
        request = self._request()
        request.baseline.evidence_ids = []
        request.baseline.verification_status = VerificationStatus.PENDING
        outcome = service.simulate(request)
        assert outcome.degraded is True
        assert any("缺少证据" in note for note in outcome.notes)

    def test_mesa_engine_is_explicitly_unavailable(self):
        with pytest.raises(SimulationEngineUnavailable):
            DigitalTwinService._build_engine("mesa")


class TestTemporalQuery:
    def test_as_of_and_diff(self):
        graph = InMemoryGraphStore()
        county = KGEntity(
            type=EntityType.COUNTY,
            name="安吉县",
            evidence_ids=["e1"],
            verification_status=VerificationStatus.VERIFIED,
        )
        industry = KGEntity(
            type=EntityType.INDUSTRY,
            name="竹产业",
            county="安吉县",
            evidence_ids=["e1"],
            verification_status=VerificationStatus.VERIFIED,
        )
        graph.upsert_entity(county)
        graph.upsert_entity(industry)
        graph.upsert_relation(
            KGRelation(
                source_entity_id=county.id,
                target_entity_id=industry.id,
                relationship_type=RelationshipType.HAS_INDUSTRY,
                source_evidence_id="e1",
                confidence=0.9,
                verification_status=VerificationStatus.VERIFIED,
                valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                valid_to=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
        query = TemporalQuery(graph)
        assert len(query.relations_as_of(datetime(2022, 1, 1, tzinfo=timezone.utc))) == 1
        assert len(query.relations_as_of(datetime(2025, 1, 1, tzinfo=timezone.utc))) == 0
        diff = query.diff(
            datetime(2022, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert len(diff.removed_relations) == 1
