from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..application.config import ResearchApplicationConfig
from ..application.research import ResearchApplication
from ..application.workflow import WorkflowRunner
from ..config import Settings, get_settings
from ..exceptions import LLMError, SearchError
from ..infrastructure.search_adapter import CollectorSearchAdapter, ProviderSearchAdapter
from ..llm.analyzer import LLMAnalyzer
from ..llm.client import OpenAICompatibleClient
from ..llm.long_history_analyzer import LongHistoryAnalyzer
from ..llm.rise_fall_analyzer import RiseFallAnalyzer
from ..mocks.llm import MockLLMClient
from ..mocks.search import MockSearchProvider
from ..modes.long_history import LongHistoryModeHandler
from ..modes.registry import ModeRegistry
from ..modes.rise_fall import RiseFallModeHandler
from ..modes.snapshot import SnapshotModeHandler
from ..pipeline import ResearchPipeline
from ..processor import DocumentProcessor
from ..reporting import ReportRenderer
from ..reporting.long_history_renderer import LongHistoryReportRenderer
from ..reporting.rise_fall_renderer import RiseFallReportRenderer
from ..search.collector import SearchCollector
from ..storage.local_fs import LocalFSStorage


class _SearchDisabledByProtocol:
    """E2 fixed-input runs 的非 Mock 搜索占位；被调用即失败。"""

    name = "disabled-by-fixed-input-protocol"

    def collect(self, *args, **kwargs):
        raise SearchError("search is disabled by the E2 fixed-input protocol")

    def collect_supplemental(self, *args, **kwargs):
        raise SearchError("search is disabled by the E2 fixed-input protocol")


def _render_filename(template: str, context: dict[str, str]) -> str:
    from jinja2 import Template

    return Template(template).render(**context)


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    llm: object
    search: object
    storage: LocalFSStorage
    application: ResearchApplication
    workflow: WorkflowRunner
    modes: ModeRegistry

    def pipeline(self) -> ResearchPipeline:
        return ResearchPipeline(
            search=self.search,
            storage=self.storage,
            llm=self.llm,
            workflow_runner=self.workflow,
        )

    def create_agent(self, *, max_steps: int = 8, save_trace: bool = True, trace_root: Path | None = None):
        from ..agent.factory import _create_agent_from_container

        return _create_agent_from_container(
            self, max_steps=max_steps, save_trace=save_trace, trace_root=trace_root
        )


def create_app_container(
    settings: Settings | None = None,
    *,
    strict_real: bool = False,
    search_enabled: bool = True,
) -> AppContainer:
    settings = settings or get_settings()
    if not search_enabled:
        search = _SearchDisabledByProtocol()
    else:
        search_key = settings.search.api_key.get_secret_value() if settings.search.api_key else ""
        if search_key:
            try:
                search = CollectorSearchAdapter(SearchCollector.from_settings(settings=settings))
            except Exception:
                if strict_real:
                    raise
                search = ProviderSearchAdapter(MockSearchProvider())
        else:
            if strict_real:
                raise SearchError("strict real container requires a search API key")
            search = ProviderSearchAdapter(MockSearchProvider())

    llm_key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else ""
    if llm_key:
        try:
            llm = OpenAICompatibleClient(settings=settings)
        except Exception:
            if strict_real:
                raise
            llm = MockLLMClient()
    else:
        if strict_real:
            raise LLMError("strict real container requires an LLM API key")
        llm = MockLLMClient()

    storage = LocalFSStorage(settings=settings)
    analyzer = LLMAnalyzer(llm=llm, settings=settings)
    renderer = ReportRenderer()
    rise_analyzer = RiseFallAnalyzer(llm=llm, settings=settings)
    rise_renderer = RiseFallReportRenderer()
    history_analyzer = LongHistoryAnalyzer(llm=llm, settings=settings)
    history_renderer = LongHistoryReportRenderer()
    modes = ModeRegistry([
        SnapshotModeHandler(analyzer, renderer, search=search),
        RiseFallModeHandler(rise_analyzer, rise_renderer, search=search),
        LongHistoryModeHandler(history_analyzer, history_renderer, search=search),
    ])
    application = ResearchApplication(
        search=search,
        storage=storage,
        processor=DocumentProcessor(quality_config=settings.quality),
        discovery=analyzer,
        modes=modes,
        config=ResearchApplicationConfig(
            max_search_results=settings.search.max_results,
            cache_enabled=settings.cache.enabled,
            cache_ttl_hours=settings.cache.ttl_hours,
            report_filename_template=settings.app.report_filename_template,
        ),
        render_filename=_render_filename,
    )
    workflow = WorkflowRunner(
        application=application,
        stages=settings.pipeline.stages,
        fail_fast=settings.pipeline.fail_fast,
    )
    return AppContainer(settings, llm, search, storage, application, workflow, modes)
