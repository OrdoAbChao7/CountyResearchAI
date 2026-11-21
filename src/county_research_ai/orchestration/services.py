"""编排层运行期依赖。

这些服务是长生命周期、可共享的；每次研究会话另有独立的
EvidenceService / GapRadarService / AgentContext。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agents.tools import ToolRegistry
from ..config import Settings
from ..knowledge_graph.entity_resolution.resolver import EntityResolver
from ..knowledge_graph.extraction.entity_extractor import EntityExtractor
from ..knowledge_graph.extraction.relation_extractor import RelationExtractor
from ..knowledge_graph.graph_store.base import GraphStore
from ..services.analytics_service import AnalyticsService
from ..services.discovery_service import DiscoveryService
from ..services.document_service import DocumentService
from ..services.evidence_service import EvidenceService
from ..services.graph_builder import KnowledgeGraphBuilder
from ..services.graph_service import GraphService, ThreadLocalEvidenceLookup
from ..services.opportunity_service import GapRadarService
from ..services.quant_service import QuantService
from ..services.report_service import ReportService
from ..services.search_service import SearchService


@dataclass
class OrchestrationServices:
    settings: Settings
    llm: Any
    # Mock LLM 不参与 Agent 的 JSON 行动循环；None 表示直接使用确定性降级，
    # 避免把 mock 文本误当作研究结论。
    agents_llm: Any
    search: SearchService
    documents: DocumentService
    analytics: AnalyticsService
    discovery: DiscoveryService
    reports: ReportService
    graph: GraphService
    graph_store: GraphStore
    graph_evidence: ThreadLocalEvidenceLookup
    quant: QuantService
    tools: ToolRegistry
    entity_extractor: EntityExtractor
    relation_extractor: RelationExtractor
    resolver: EntityResolver

    # ---- 每运行实例 ----

    def new_evidence(self) -> EvidenceService:
        return EvidenceService()

    def new_gap_radar(self, evidence: EvidenceService) -> GapRadarService:
        return GapRadarService(self.graph_store, evidence, self.quant)

    def new_graph_builder(self) -> KnowledgeGraphBuilder:
        return KnowledgeGraphBuilder(
            self.graph_store,
            self.entity_extractor,
            self.relation_extractor,
            self.resolver,
            max_docs=max(5, min(self.settings.agents.max_steps * 4, 40)),
            allow_inferred=False,
        )


__all__ = ["OrchestrationServices"]
