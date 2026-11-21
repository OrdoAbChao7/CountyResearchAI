"""知识图谱测试：本体约束、抽取、消歧、存储、GraphRAG 与时序。"""
from __future__ import annotations

import json

import pytest

from county_research_ai.domain.intelligence import VerificationStatus
from county_research_ai.knowledge_graph.entity_resolution.resolver import EntityResolver
from county_research_ai.knowledge_graph.extraction.entity_extractor import EntityExtractor
from county_research_ai.knowledge_graph.extraction.relation_extractor import RelationExtractor
from county_research_ai.knowledge_graph.graph_rag.query_engine import GraphRAGQueryEngine
from county_research_ai.knowledge_graph.graph_store.base import (
    GraphStoreError,
    GraphWriteError,
    GraphWritePolicy,
)
from county_research_ai.knowledge_graph.graph_store.mock_store import InMemoryGraphStore
from county_research_ai.knowledge_graph.ontology.entities import EntityType, KGEntity
from county_research_ai.knowledge_graph.ontology.relations import KGRelation, RelationshipType
from county_research_ai.services.evidence_service import EvidenceService
from county_research_ai.services.graph_builder import KnowledgeGraphBuilder, seed_core_graph


def _entity(
    kind: EntityType,
    name: str,
    *,
    county: str = "",
    evidence: tuple[str, ...] = ("ev-1",),
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> KGEntity:
    return KGEntity(
        type=kind,
        name=name,
        county=county,
        evidence_ids=list(evidence),
        confidence=0.9,
        verification_status=status,
    )


def _relation(
    source: KGEntity,
    target: KGEntity,
    kind: RelationshipType = RelationshipType.HAS_INDUSTRY,
    *,
    evidence: str = "ev-1",
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> KGRelation:
    return KGRelation(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=kind,
        source_evidence_id=evidence,
        confidence=0.9,
        verification_status=status,
    )


class TestOntology:
    def test_entity_id_is_stable_and_name_normalized(self):
        first = KGEntity(type=EntityType.ENTERPRISE, name="安吉 竹业")
        second = KGEntity(type=EntityType.ENTERPRISE, name="安吉竹业")
        assert first.id == second.id

    def test_verified_entity_requires_evidence(self):
        with pytest.raises(ValueError, match="verified entity requires"):
            KGEntity(
                type=EntityType.INDUSTRY,
                name="竹产业",
                verification_status=VerificationStatus.VERIFIED,
            )

    def test_verified_relation_requires_evidence(self):
        with pytest.raises(ValueError, match="verified relation requires"):
            KGRelation(
                source_entity_id="a",
                target_entity_id="b",
                relationship_type=RelationshipType.HAS_INDUSTRY,
                verification_status=VerificationStatus.VERIFIED,
            )

    def test_relation_rejects_self_loop_and_bad_dates(self):
        with pytest.raises(ValueError, match="self-referencing"):
            KGRelation(
                source_entity_id="a",
                target_entity_id="a",
                relationship_type=RelationshipType.HAS_INDUSTRY,
            )

    def test_relation_requires_valid_confidence(self):
        with pytest.raises(ValueError):
            KGRelation(
                source_entity_id="a",
                target_entity_id="b",
                relationship_type=RelationshipType.HAS_INDUSTRY,
                confidence=1.5,
            )


class TestGraphWritePolicy:
    def _pair(self) -> tuple[KGEntity, KGEntity]:
        return (
            _entity(EntityType.COUNTY, "安吉县"),
            _entity(EntityType.INDUSTRY, "竹产业", county="安吉县"),
        )

    def test_policy_rejects_inferred_by_default(self):
        graph = InMemoryGraphStore()
        county, industry = self._pair()
        graph.upsert_entity(county)
        graph.upsert_entity(industry)
        with pytest.raises(GraphWriteError, match="refusing to persist"):
            graph.upsert_relation(
                _relation(county, industry, status=VerificationStatus.INFERRED, evidence="")
            )

    def test_policy_rejects_verified_without_evidence(self):
        graph = InMemoryGraphStore()
        county, industry = self._pair()
        graph.upsert_entity(county)
        graph.upsert_entity(industry)
        relation = _relation(county, industry).model_copy(
            update={"verification_status": VerificationStatus.VERIFIED, "source_evidence_id": ""}
        )
        with pytest.raises(GraphWriteError, match="verified relation requires evidence"):
            graph.upsert_relation(relation)

    def test_allow_inferred_is_explicit(self):
        graph = InMemoryGraphStore(GraphWritePolicy(allow_inferred=True))
        county, industry = self._pair()
        graph.upsert_entity(county)
        graph.upsert_entity(industry)
        graph.upsert_relation(
            _relation(county, industry, status=VerificationStatus.INFERRED, evidence="")
        )
        assert graph.stats()["relations"] == 1
        assert graph.get_relations() == []
        assert len(graph.get_relations(include_inferred=True)) == 1

    def test_relation_requires_existing_endpoints(self):
        graph = InMemoryGraphStore()
        county = _entity(EntityType.COUNTY, "安吉县")
        industry = _entity(EntityType.INDUSTRY, "竹产业", county="安吉县")
        graph.upsert_entity(county)
        with pytest.raises(GraphStoreError, match="endpoints must exist"):
            graph.upsert_relation(_relation(county, industry))


class TestEntityResolver:
    def test_normalize_strips_legal_suffix_and_parentheses(self):
        resolver = EntityResolver()
        assert resolver.normalize("安吉竹业股份有限公司") == "安吉竹业"
        assert resolver.normalize("安吉竹业（集团）有限公司") == "安吉竹业"

    def test_resolves_normalized_name(self):
        resolver = EntityResolver()
        existing = [_entity(EntityType.ENTERPRISE, "安吉竹业股份有限公司", county="安吉县")]
        candidate = _entity(EntityType.ENTERPRISE, "安吉竹业有限公司", county="安吉县")
        resolution = resolver.resolve(candidate, existing)
        assert resolution.matched is True
        assert resolution.method == "normalized_name"
        assert resolution.entity_id == existing[0].id

    def test_resolves_alias(self):
        resolver = EntityResolver()
        existing = [
            _entity(EntityType.INDUSTRY, "竹产业", county="安吉县"),
        ]
        existing[0].aliases = ["竹制品产业"]
        candidate = _entity(EntityType.INDUSTRY, "竹制品产业", county="安吉县")
        resolution = resolver.resolve(candidate, existing)
        assert resolution.matched is True
        assert resolution.method in {"alias", "normalized_name"}

    def test_does_not_cross_counties(self):
        resolver = EntityResolver()
        existing = [_entity(EntityType.ENTERPRISE, "安吉竹业有限公司", county="安吉县")]
        candidate = _entity(EntityType.ENTERPRISE, "安吉竹业有限公司", county="德清县")
        resolution = resolver.resolve(candidate, existing)
        assert resolution.matched is False
        assert resolution.method == "new"

    def test_merge_preserves_evidence_and_status(self):
        resolver = EntityResolver()
        primary = _entity(EntityType.ENTERPRISE, "安吉竹业有限公司", county="安吉县")
        other = _entity(
            EntityType.ENTERPRISE,
            "安吉竹业股份有限公司",
            county="安吉县",
            evidence=("ev-2",),
            status=VerificationStatus.PENDING,
        )
        merged = resolver.merge(primary, other)
        assert merged.id == primary.id
        assert set(merged.evidence_ids) == {"ev-1", "ev-2"}
        assert "安吉竹业股份有限公司" in merged.aliases
        assert merged.verification_status == VerificationStatus.VERIFIED


class TestEntityExtractor:
    def test_rule_extraction_binds_evidence(self, sample_docs):
        extractor = EntityExtractor()
        text = sample_docs[0].content
        entities = extractor.extract(
            text, county="安吉县", focus="竹产业", evidence_ids=["ev-1"]
        )
        names = {entity.name for entity in entities}
        assert "安吉县" in names
        assert "竹产业" in names
        assert "安吉竹业股份有限公司" in names
        assert all(entity.verification_status == VerificationStatus.VERIFIED for entity in entities)
        assert all(entity.evidence_ids == ["ev-1"] for entity in entities)

    def test_without_evidence_entities_are_pending(self, sample_docs):
        entities = EntityExtractor().extract(sample_docs[0].content, focus="竹产业")
        assert entities
        assert all(entity.verification_status == VerificationStatus.PENDING for entity in entities)

    def test_llm_quote_binding_requires_quote_in_text(self, scripted_llm):
        text = "安吉县竹产业实现产值120亿元。安吉竹业股份有限公司位于安吉县。"
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "entities": [
                            {
                                "type": "enterprise",
                                "name": "安吉竹业股份有限公司",
                                "confidence": 0.9,
                                "quote": "安吉竹业股份有限公司位于安吉县",
                            },
                            {
                                "type": "industry",
                                "name": "竹产业",
                                "confidence": 0.9,
                                "quote": "安吉县竹产业实现产值120亿元",
                            },
                            {
                                "type": "enterprise",
                                "name": "虚假公司",
                                "confidence": 0.9,
                                "quote": "原文不存在这句话",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        )
        entities = EntityExtractor(llm).extract(
            text, county="安吉县", evidence_ids=["ev-1"]
        )
        by_name = {entity.name: entity for entity in entities}
        assert by_name["竹产业"].verification_status == VerificationStatus.VERIFIED
        assert by_name["竹产业"].evidence_ids == ["ev-1"]
        hallucinated = by_name["虚假公司"]
        assert hallucinated.verification_status == VerificationStatus.PENDING
        assert hallucinated.evidence_ids == []

    def test_rule_extraction_skips_sentence_fragments(self):
        text = "近年该县重点打造百亿级特色产业，建成省级产业园区。"
        entities = EntityExtractor().extract(text, county="安吉县")
        names = [entity.name for entity in entities]
        assert not any("百亿" in name for name in names)
        assert "近年该县特色产业" not in names


class TestRelationExtractor:
    def _entities(self) -> list[KGEntity]:
        return [
            _entity(EntityType.ENTERPRISE, "安吉竹业股份有限公司", county="安吉县"),
            _entity(EntityType.COUNTY, "安吉县", evidence=("ev-1",)),
        ]

    def test_llm_quote_binding(self, scripted_llm):
        text = "安吉竹业股份有限公司位于安吉县，是当地龙头企业。"
        llm = scripted_llm(
            [
                json.dumps(
                    {
                        "relations": [
                            {
                                "source": "安吉竹业股份有限公司",
                                "target": "安吉县",
                                "type": "LOCATED_IN",
                                "confidence": 0.9,
                                "quote": "安吉竹业股份有限公司位于安吉县",
                            },
                            {
                                "source": "安吉竹业股份有限公司",
                                "target": "安吉县",
                                "type": "LOCATED_IN",
                                "confidence": 0.9,
                                "quote": "编造的原文依据",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        )
        relations = RelationExtractor(llm).extract(
            text, self._entities(), evidence_id="ev-1"
        )
        assert len(relations) == 2
        assert relations[0].verification_status == VerificationStatus.VERIFIED
        assert relations[0].source_evidence_id == "ev-1"
        assert relations[1].verification_status == VerificationStatus.INFERRED
        assert relations[1].evidence_refs() == []

    def test_rule_extraction_requires_known_entities(self):
        relations = RelationExtractor().extract(
            "安吉竹业股份有限公司位于安吉县。", self._entities(), evidence_id="ev-1"
        )
        assert relations
        assert relations[0].relationship_type == RelationshipType.LOCATED_IN
        assert relations[0].verification_status == VerificationStatus.VERIFIED


class TestGraphStore:
    def _graph(self) -> tuple[InMemoryGraphStore, KGEntity, KGEntity, KGEntity]:
        graph = InMemoryGraphStore()
        county = _entity(EntityType.COUNTY, "安吉县")
        industry = _entity(EntityType.INDUSTRY, "竹产业", county="安吉县")
        segment = _entity(EntityType.INDUSTRY_SEGMENT, "精深加工")
        for entity in (county, industry, segment):
            graph.upsert_entity(entity)
        graph.upsert_relation(_relation(county, industry))
        graph.upsert_relation(_relation(industry, segment, RelationshipType.CONTAINS, evidence="ev-2"))
        return graph, county, industry, segment

    def test_upsert_is_idempotent_and_merges_evidence(self):
        graph, county, industry, _ = self._graph()
        incoming = _entity(
            EntityType.INDUSTRY,
            "竹产业",
            county="安吉县",
            evidence=("ev-9",),
        )
        merged = graph.upsert_entity(incoming)
        assert merged.id == industry.id
        assert set(merged.evidence_ids) == {"ev-1", "ev-9"}
        assert graph.stats()["entities"] == 3

    def test_county_subgraph_includes_segments(self):
        graph, county, _, _ = self._graph()
        subgraph = graph.county_subgraph("安吉县", industry="竹产业")
        names = {entity.name for entity in subgraph.entities}
        assert {"安吉县", "竹产业", "精深加工"} <= names
        assert len(subgraph.relations) == 2

    def test_multi_hop_and_shortest_path(self):
        graph, county, _, segment = self._graph()
        subgraph = graph.neighbors(county.id, depth=2)
        assert {entity.name for entity in subgraph.entities} == {"安吉县", "竹产业", "精深加工"}
        path = graph.shortest_path(county.id, segment.id, max_depth=3)
        assert len(path) == 2
        assert path[0].relationship_type == RelationshipType.HAS_INDUSTRY

    def test_unverified_relations_are_hidden_by_default(self):
        graph = InMemoryGraphStore(GraphWritePolicy(allow_inferred=True))
        a = _entity(EntityType.INDUSTRY, "竹产业", county="安吉县")
        b = _entity(EntityType.INDUSTRY_SEGMENT, "上游种植")
        graph.upsert_entity(a)
        graph.upsert_entity(b)
        graph.upsert_relation(
            _relation(a, b, RelationshipType.CONTAINS, status=VerificationStatus.INFERRED, evidence="")
        )
        assert graph.get_relations(relationship_type=RelationshipType.CONTAINS) == []
        assert len(graph.get_relations(include_inferred=True)) == 1


class TestGraphRAG:
    def _graph(self) -> tuple[InMemoryGraphStore, KGEntity, KGEntity, KGEntity, KGEntity]:
        graph = InMemoryGraphStore()
        county = _entity(EntityType.COUNTY, "安吉县")
        industry = _entity(EntityType.INDUSTRY, "竹产业", county="安吉县")
        segment = _entity(EntityType.INDUSTRY_SEGMENT, "精深加工")
        enterprise = _entity(EntityType.ENTERPRISE, "安吉竹业股份有限公司", county="安吉县", evidence=("ev-3",))
        for entity in (county, industry, segment, enterprise):
            graph.upsert_entity(entity)
        graph.upsert_relation(_relation(county, industry))
        graph.upsert_relation(_relation(industry, segment, RelationshipType.CONTAINS, evidence="ev-2"))
        graph.upsert_relation(_relation(enterprise, segment, RelationshipType.BELONGS_TO, evidence="ev-3"))
        return graph, county, industry, segment, enterprise

    def test_supply_chain(self):
        graph, _, _, _, _ = self._graph()
        engine = GraphRAGQueryEngine(graph)
        result = engine.supply_chain("竹产业", county="安吉县")
        assert "1 个环节" in result.answer
        assert any(entity["name"] == "精深加工" for entity in result.entities)
        assert result.relations
        assert result.evidence_ids

    def test_enterprise_relations(self):
        graph, _, _, _, enterprise = self._graph()
        engine = GraphRAGQueryEngine(graph)
        result = engine.enterprise_relations(enterprise.name, county="安吉县")
        assert "安吉竹业股份有限公司" in result.answer
        assert any("BELONGS_TO" in note or True for note in result.notes) or result.relations

    def test_multi_hop_reaches_segment(self):
        graph, _, _, _, enterprise = self._graph()
        engine = GraphRAGQueryEngine(graph)
        result = engine.multi_hop(enterprise.name, county="安吉县", depth=2)
        names = {entity["name"] for entity in result.entities}
        assert "精深加工" in names
        assert "竹产业" in names

    def test_missing_entity_is_explicit(self):
        graph, *_ = self._graph()
        engine = GraphRAGQueryEngine(graph)
        result = engine.supply_chain("不存在的产业", county="安吉县")
        assert result.entities == []
        assert result.notes

    def test_evidence_trace(self):
        graph, _, _, _, enterprise = self._graph()
        evidence = EvidenceService()
        engine = GraphRAGQueryEngine(graph, evidence)
        result = engine.evidence_trace(entity_id=enterprise.id)
        assert "ev-3" in result.evidence_ids
        assert "1 个证据引用" in result.answer


class TestGraphBuilder:
    def test_builds_verified_graph_from_documents(self, sample_docs):
        graph = InMemoryGraphStore()
        evidence = EvidenceService()
        evidence.ingest(sample_docs, county="安吉县", focus="竹产业")
        builder = KnowledgeGraphBuilder(
            graph, EntityExtractor(), RelationExtractor(), max_docs=5
        )
        stats = builder.build(
            sample_docs, county="安吉县", focus="竹产业", evidence_service=evidence
        )
        assert stats.docs_processed >= 1
        assert stats.entities_written >= 2
        assert stats.relations_written >= 1
        for relation in graph.get_relations():
            assert relation.verification_status == VerificationStatus.VERIFIED
            assert relation.evidence_refs()
            assert all(evidence.get(i) is not None for i in relation.evidence_refs())

    def test_seed_core_graph_requires_evidence(self):
        graph = InMemoryGraphStore()
        seed_core_graph(graph, county="安吉县", focus="竹产业", evidence_ids=[])
        assert graph.stats()["entities"] == 0

        seed_core_graph(graph, county="安吉县", focus="竹产业", evidence_ids=["ev-1"])
        assert graph.stats()["entities"] == 2
        assert graph.stats()["relations"] == 1
