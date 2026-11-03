"""ResearchPipeline 兼容门面。

实际编排由 WorkflowRunner 完成，业务阶段由 ResearchApplication 提供。
本模块只保留历史构造参数和公开返回值，避免旧调用方迁移成本。
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path

from .application.config import ResearchApplicationConfig
from .application.research import ResearchApplication
from .application.workflow import WorkflowRunner
from .config import get_settings
from .infrastructure.search_adapter import CollectorSearchAdapter, ProviderSearchAdapter
from .llm.analyzer import LLMAnalyzer
from .llm.base import LLMClient
from .llm.long_history_analyzer import LongHistoryAnalyzer
from .llm.rise_fall_analyzer import RiseFallAnalyzer
from .mocks import MockLLMClient, MockSearchProvider, MockStorage
from .models import ResearchReport, ResearchRequest
from .modes.long_history import LongHistoryModeHandler
from .modes.registry import ModeRegistry
from .modes.rise_fall import RiseFallModeHandler
from .modes.snapshot import SnapshotModeHandler
from .processor import DocumentProcessor
from .reporting import ReportRenderer
from .reporting.long_history_renderer import LongHistoryReportRenderer
from .reporting.rise_fall_renderer import RiseFallReportRenderer
from .search.base import SearchProvider
from .storage.base import Storage

logger = logging.getLogger(__name__)


class ResearchPipeline:
    """旧 Pipeline API 的薄兼容层。"""

    def __init__(
        self,
        *,
        search: SearchProvider,
        storage: Storage,
        llm: LLMClient,
        analyzer: LLMAnalyzer | None = None,
        renderer: ReportRenderer | None = None,
        rise_fall_analyzer: RiseFallAnalyzer | None = None,
        rise_fall_renderer: RiseFallReportRenderer | None = None,
        long_history_analyzer: LongHistoryAnalyzer | None = None,
        long_history_renderer: LongHistoryReportRenderer | None = None,
        workflow_runner: WorkflowRunner | None = None,
    ) -> None:
        settings = get_settings()
        self.search = getattr(search, "provider", getattr(search, "collector", search))
        self.storage = storage
        self.llm = llm
        self.analyzer = analyzer or LLMAnalyzer(llm=llm, settings=settings)
        self.renderer = renderer or ReportRenderer()
        self.rise_fall_analyzer = rise_fall_analyzer or RiseFallAnalyzer(llm=llm, settings=settings)
        self.rise_fall_renderer = rise_fall_renderer or RiseFallReportRenderer()
        self.long_history_analyzer = long_history_analyzer or LongHistoryAnalyzer(llm=llm, settings=settings)
        self.long_history_renderer = long_history_renderer or LongHistoryReportRenderer()

        search_port = search
        if not hasattr(search_port, "collect"):
            search_port = ProviderSearchAdapter(search_port)
        elif not isinstance(search_port, (CollectorSearchAdapter, ProviderSearchAdapter)):
            search_port = CollectorSearchAdapter(search_port)
        modes = ModeRegistry([
            SnapshotModeHandler(self.analyzer, self.renderer, search=search_port),
            RiseFallModeHandler(self.rise_fall_analyzer, self.rise_fall_renderer, search=search_port),
            LongHistoryModeHandler(self.long_history_analyzer, self.long_history_renderer, search=search_port),
        ])
        self.application = ResearchApplication(
            search=search_port,
            storage=storage,
            processor=DocumentProcessor(quality_config=settings.quality),
            discovery=self.analyzer,
            modes=modes,
            config=ResearchApplicationConfig(
                max_search_results=settings.search.max_results,
                cache_enabled=settings.cache.enabled,
                cache_ttl_hours=settings.cache.ttl_hours,
                report_filename_template=settings.app.report_filename_template,
            ),
            render_filename=self.renderer.render_filename,
        )
        self.workflow_runner = workflow_runner or WorkflowRunner(
            application=self.application,
            stages=settings.pipeline.stages,
            fail_fast=settings.pipeline.fail_fast,
        )
        self.application = self.workflow_runner.application

    def run(self, request: ResearchRequest) -> tuple[ResearchReport, Path]:
        result = self.workflow_runner.run(request)
        return result.report, result.report_path


def create_default_pipeline() -> ResearchPipeline:
    """通过统一应用容器创建默认研究 Pipeline。"""
    from .bootstrap.container import create_app_container

    return create_app_container(get_settings()).pipeline()


def setup_logging() -> None:
    settings = get_settings()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"standard": {"format": settings.logging.format, "datefmt": settings.logging.date_format}},
        "handlers": {"console": {"class": "logging.StreamHandler", "level": settings.logging.level, "formatter": "standard"}},
        "loggers": {"": {"handlers": ["console"], "level": settings.logging.level, "propagate": True}},
    })


__all__ = [
    "MockLLMClient", "MockSearchProvider", "MockStorage", "ResearchPipeline",
    "create_default_pipeline", "setup_logging",
]
