"""独立业务服务层。

旧架构把这些能力绑在 ``ResearchApplication`` / ``WorkflowRunner`` 上；
V2 把它们拆成无状态或运行期绑定的服务，由 Agent Tools 直接调用。
"""
from .analytics_service import AnalyticsService
from .discovery_service import DiscoveryService
from .document_service import DocumentService
from .evidence_service import EvidenceService
from .graph_builder import GraphBuildStats, KnowledgeGraphBuilder, seed_core_graph
from .graph_service import GraphService, ThreadLocalEvidenceLookup
from .opportunity_service import GapRadarService
from .quant_service import QuantService
from .report_service import ReportService
from .search_service import SearchService

__all__ = [
    "AnalyticsService",
    "DiscoveryService",
    "DocumentService",
    "EvidenceService",
    "GapRadarService",
    "GraphBuildStats",
    "GraphService",
    "KnowledgeGraphBuilder",
    "QuantService",
    "ReportService",
    "SearchService",
    "ThreadLocalEvidenceLookup",
    "seed_core_graph",
]
