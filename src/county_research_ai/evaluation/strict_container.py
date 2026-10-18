"""只允许真实 Provider 的实验容器。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..bootstrap.container import AppContainer, create_app_container
from ..config import Settings
from ..exceptions import SearchError
from .providers import ResourceManagedLLMClient, ResourceManagedSearchProvider
from .resource_manager import ResourceManager


@dataclass(frozen=True)
class StrictRealContainer:
    app: AppContainer
    instrumented_llm: Any | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        resource_manager: ResourceManager | None = None,
        run_id: str | None = None,
        artifact_dir: Path | None = None,
        search_enabled: bool = True,
    ) -> StrictRealContainer:
        app = create_app_container(
            settings,
            strict_real=True,
            search_enabled=search_enabled,
        )
        cls.assert_no_mock(app.llm, app.search)
        if resource_manager is None or run_id is None:
            return cls(app)

        current_settings = settings or app.settings
        managed_llm = ResourceManagedLLMClient(
            app.llm,
            manager=resource_manager,
            provider=current_settings.llm.provider,
            model=current_settings.llm.model,
            run_id=run_id,
            artifact_dir=artifact_dir,
        )
        cls._replace_llm(app, managed_llm)
        if search_enabled:
            cls._replace_search(app, resource_manager, run_id)
        return cls(app, instrumented_llm=managed_llm)

    @property
    def llm(self) -> Any:
        return self.app.llm

    @property
    def search(self) -> Any:
        return self.app.search

    @staticmethod
    def assert_no_mock(llm: Any, search: Any) -> None:
        candidates = [llm, search]
        candidates.extend(
            component
            for component in (
                getattr(search, "provider", None),
                getattr(getattr(search, "collector", None), "_web", None),
                getattr(getattr(search, "collector", None), "_gov", None),
            )
            if component is not None
        )
        for component in candidates:
            class_name = type(component).__name__.lower()
            module_name = type(component).__module__.lower()
            name = str(getattr(component, "name", "")).lower()
            if class_name.startswith("mock") or ".mocks" in module_name or name.startswith("mock"):
                raise SearchError(
                    "Mock component detected in strict real container",
                    context={"component_type": type(component).__name__},
                )

    @staticmethod
    def _replace_llm(app: AppContainer, managed_llm: ResourceManagedLLMClient) -> None:
        app.application.discovery._llm = managed_llm
        for handler in app.modes._handlers.values():
            analyzer = getattr(handler, "analyzer", None)
            if hasattr(analyzer, "_llm"):
                analyzer._llm = managed_llm

    @staticmethod
    def _replace_search(
        app: AppContainer,
        resource_manager: ResourceManager,
        run_id: str,
    ) -> None:
        collector = getattr(app.search, "collector", None)
        web_provider = getattr(collector, "_web", None)
        if collector is None or web_provider is None:
            raise SearchError("strict real experiment requires a collector-backed search provider")
        managed_web = ResourceManagedSearchProvider(
            web_provider,
            manager=resource_manager,
            provider=app.settings.search.provider,
            run_id=run_id,
        )
        collector._web = managed_web
        if getattr(collector, "_gov", None) is not None:
            collector._gov._web = managed_web
