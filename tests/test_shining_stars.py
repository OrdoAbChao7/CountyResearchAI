"""三大 Shining Stars 的契约测试。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from county_research_ai.domain.intelligence import VerificationStatus
from county_research_ai.knowledge_graph.graph_store.mock_store import InMemoryGraphStore
from county_research_ai.knowledge_graph.ontology.entities import EntityType, KGEntity
from county_research_ai.knowledge_graph.ontology.relations import KGRelation, RelationshipType
from county_research_ai.knowledge_graph.temporal.models import ChangeType, TemporalQuery
from county_research_ai.shining_stars import (
    DigitalTwinService,
    GapRadarService,
    OpportunityReport,
    SimulationRequest,
)
from county_research_ai.shining_stars import (
    TemporalQuery as ExportedTemporalQuery,
)
from county_research_ai.shining_stars.digital_twin import (
    BaselineProfile,
    SimulationEngineUnavailable,
    SimulationScenario,
)


def _simulation(**overrides) -> SimulationRequest:
    baseline = {
        "county": "安吉县",
        "industry": "竹产业",
        "output_yi": 100,
        "growth_rate": 0.1,
        "employment": 10000,
        "enterprise_count": 80,
        "source_year": 2025,
        "evidence_ids": ["ev-1"],
        "verification_status": VerificationStatus.VERIFIED,
    }
    baseline.update(overrides)
    return SimulationRequest(
        baseline=BaselineProfile(**baseline),
        scenario=SimulationScenario(name="baseline", horizon_years=3),
    )


class TestDigitalTwin:
    def test_capabilities_declare_boundaries(self, tmp_settings):
        service = DigitalTwinService(settings=tmp_settings)
        capabilities = service.capabilities()
        assert capabilities["engine"] == "baseline"
        assert capabilities["calibrated"] is False
        assert "mesa_boundary" in capabilities
        assert "industrial_output" in capabilities["supported_variables"]

    def test_baseline_is_deterministic_and_marked_inferred(self, tmp_settings):
        service = DigitalTwinService(settings=tmp_settings)
        first = service.simulate(_simulation())
        second = service.simulate(_simulation())
        assert [p.output_yi for p in first.projections] == [
            p.output_yi for p in second.projections
        ]
        assert first.verification_status == VerificationStatus.INFERRED
        assert first.metadata["calibrated"] is False
        assert first.model_type == "deterministic_accounting_baseline"

    def test_missing_evidence_marks_degraded(self, tmp_settings):
        service = DigitalTwinService(settings=tmp_settings)
        request = _simulation(
            evidence_ids=[], verification_status=VerificationStatus.PENDING
        )
        outcome = service.simulate(request)
        assert outcome.degraded is True
        assert any("缺少证据" in note for note in outcome.notes)

    def test_disabled_and_unbounded_requests_are_rejected(self, tmp_settings):
        service = DigitalTwinService(settings=tmp_settings)
        long_request = _simulation()
        long_request.scenario.horizon_years = 21
        with pytest.raises(ValueError, match="horizon_years"):
            service.simulate(long_request)

        tmp_settings.simulation.enabled = False
        with pytest.raises(SimulationEngineUnavailable, match="disabled"):
            service.simulate(_simulation())

    def test_mesa_is_not_faked(self):
        with pytest.raises(SimulationEngineUnavailable, match="Mesa"):
            DigitalTwinService._build_engine("mesa")


class TestTemporalIntelligence:
    def _graph_with_timeline(self):
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
        relation = KGRelation(
            source_entity_id=county.id,
            target_entity_id=industry.id,
            relationship_type=RelationshipType.HAS_INDUSTRY,
            source_evidence_id="e1",
            confidence=0.9,
            verification_status=VerificationStatus.VERIFIED,
            valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        graph.upsert_relation(relation)
        return graph, county, industry, relation

    def test_snapshot_and_count(self):
        graph, county, _, _ = self._graph_with_timeline()
        query = TemporalQuery(graph)
        snapshot = query.snapshot_as_of(datetime(2022, 6, 1, tzinfo=timezone.utc))
        assert {entity.name for entity in snapshot.entities} == {"安吉县", "竹产业"}
        assert snapshot.evidence_ids == ["e1"]
        assert query.verified_relation_count(datetime(2022, 6, 1, tzinfo=timezone.utc)) == 1
        assert query.verified_relation_count(datetime(2025, 1, 1, tzinfo=timezone.utc)) == 0

    def test_history_marks_invalidated_relations(self):
        graph, county, _, _ = self._graph_with_timeline()
        versions = TemporalQuery(graph).entity_history(county.id)
        assert versions
        assert versions[0].change_type == ChangeType.INVALIDATED
        assert versions[0].valid_to is not None

    def test_diff_detects_removed_relation(self):
        graph, *_ = self._graph_with_timeline()
        diff = TemporalQuery(graph).diff(
            datetime(2022, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert len(diff.removed_relations) == 1
        assert diff.added_relations == []
        assert diff.removed_entities

    def test_star_exports_are_the_same_contracts(self):
        assert ExportedTemporalQuery is TemporalQuery
        assert OpportunityReport is not None
        assert GapRadarService is not None
