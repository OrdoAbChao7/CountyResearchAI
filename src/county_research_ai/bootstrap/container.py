"""应用容器：装配 V2 服务、知识图谱、Agent 工具与运行服务。

容器不再包含 WorkflowRunner / ResearchApplication / CLI。所有外部依赖
缺失时自动降级为 Mock 或内存实现，保证 API 与测试可以离线运行。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..agents.tools import build_default_tools
from ..config import Settings, get_settings
from ..knowledge_graph.entity_resolution.resolver import EntityResolver
from ..knowledge_graph.extraction.entity_extractor import EntityExtractor
from ..knowledge_graph.extraction.relation_extractor import RelationExtractor
from ..knowledge_graph.graph_rag.query_engine import GraphRAGQueryEngine
from ..knowledge_graph.graph_store import create_graph_store
from ..knowledge_graph.graph_store.base import GraphStore
from ..llm.analyzer import LLMAnalyzer
from ..llm.client import OpenAICompatibleClient
from ..llm.long_history_analyzer import LongHistoryAnalyzer
from ..llm.rise_fall_analyzer import RiseFallAnalyzer
from ..mocks.llm import MockLLMClient
from ..orchestration.runner import ResearchRunService
from ..orchestration.services import OrchestrationServices
from ..processor import DocumentProcessor
from ..services.analytics_service import AnalyticsService
from ..services.discovery_service import DiscoveryService
from ..services.document_service import DocumentService
from ..services.graph_service import GraphService, ThreadLocalEvidenceLookup
from ..services.quant_service import QuantService
from ..services.report_service import ReportService
from ..services.search_service import SearchService, build_search_service
from ..shining_stars.digital_twin import DigitalTwinService
from ..storage.local_fs import LocalFSStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    llm: Any
    search: SearchService
    storage: LocalFSStorage
    graph_store: GraphStore
    services: OrchestrationServices
    runs: ResearchRunService
    simulation: DigitalTwinService

    def close(self) -> None:
        self.runs.shutdown()
        closer = getattr(self.graph_store, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                logger.debug("关闭图存储失败", exc_info=True)


def build_llm(settings: Settings) -> Any:
    api_key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    if not api_key:
        logger.info("未配置 LLM_API_KEY，使用 MockLLMClient（Agent 将走确定性降级）")
        return MockLLMClient()
    try:
        return OpenAICompatibleClient(settings=settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 客户端初始化失败，使用 MockLLMClient | err=%s", exc)
        return MockLLMClient()


def create_services(
    settings: Settings | None = None,
    *,
    llm: Any = None,
    search: SearchService | None = None,
    graph_store: GraphStore | None = None,
) -> OrchestrationServices:
    settings = settings or get_settings()
    llm = llm if llm is not None else build_llm(settings)
    search = search or build_search_service(settings)
    storage = LocalFSStorage(settings=settings)
    graph_store = graph_store or create_graph_store(settings)

    analyzer = LLMAnalyzer(llm=llm, settings=settings)
    analytics = AnalyticsService(
        snapshot_analyzer=analyzer,
        rise_fall_analyzer=RiseFallAnalyzer(llm=llm, settings=settings),
        long_history_analyzer=LongHistoryAnalyzer(llm=llm, settings=settings),
    )
    documents = DocumentService(
        DocumentProcessor(quality_config=settings.quality), storage, settings
    )
    reports = ReportService(storage)
    agent_llm = None if isinstance(llm, MockLLMClient) else llm
    graph_evidence = ThreadLocalEvidenceLookup()
    query_engine = GraphRAGQueryEngine(
        graph_store, evidence=graph_evidence, llm=agent_llm
    )
    graph_service = GraphService(graph_store, query_engine)

    return OrchestrationServices(
        settings=settings,
        llm=llm,
        agents_llm=agent_llm,
        search=search,
        documents=documents,
        analytics=analytics,
        discovery=DiscoveryService(analyzer),
        reports=reports,
        graph=graph_service,
        graph_store=graph_store,
        graph_evidence=graph_evidence,
        quant=QuantService(),
        tools=build_default_tools(),
        entity_extractor=EntityExtractor(agent_llm),
        relation_extractor=RelationExtractor(agent_llm),
        resolver=EntityResolver(),
    )


def create_app_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or get_settings()
    services = create_services(settings)
    runs = ResearchRunService(services)
    return AppContainer(
        settings=settings,
        llm=services.llm,
        search=services.search,
        storage=LocalFSStorage(settings=settings),
        graph_store=services.graph_store,
        services=services,
        runs=runs,
        simulation=DigitalTwinService(settings=settings),
    )


__all__ = ["AppContainer", "build_llm", "create_app_container", "create_services"]
