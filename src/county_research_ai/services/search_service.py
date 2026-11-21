"""搜索服务:统一封装采集器、单查询搜索与补充检索。

Agent 不再通过 Workflow 触发搜索，而是通过 ``search_web`` /
``search_supplemental`` 工具调用本服务。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import Settings, get_settings
from ..domain.modes import normalize_mode
from ..exceptions import SearchError
from ..infrastructure.search_adapter import CollectorSearchAdapter, ProviderSearchAdapter
from ..models import RawDoc
from ..search.base import SearchProvider
from ..search.collector import SearchCollector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchOutcome:
    """一次检索的可审计结果。"""

    docs: list[RawDoc]
    query: str = ""
    provider: str = ""
    degraded: bool = False
    error: str = ""


class SearchService:
    """面向 Agent 的检索入口。

    Args:
        port: 已适配为 ``collect`` 接口的采集端口（CollectorSearchAdapter /
            ProviderSearchAdapter）。测试可注入任意实现。
        provider_name: 可观测的 provider 名称。
        max_results: 默认返回条数。
    """

    def __init__(
        self,
        port: object,
        *,
        provider_name: str = "unknown",
        max_results: int = 10,
        degraded: bool = False,
    ) -> None:
        self._port = port
        self.provider_name = provider_name
        self._max_results = max_results
        self.degraded = degraded

    # ---- 主接口 ----

    def collect(
        self,
        county: str,
        focus: str = "",
        *,
        mode: str = "snapshot",
        limit: int | None = None,
    ) -> SearchOutcome:
        """按县域 + 方向做多角度定向采集。"""
        limit = limit or self._max_results
        try:
            docs = self._port.collect(  # type: ignore[attr-defined]
                county, focus, limit, mode=normalize_mode(mode)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearchService.collect 失败 | county=%s | err=%s", county, exc)
            return SearchOutcome(docs=[], query=f"{county} {focus}".strip(),
                                 provider=self.provider_name, degraded=True, error=str(exc))
        return SearchOutcome(
            docs=docs,
            query=f"{county} {focus}".strip(),
            provider=self.provider_name,
            degraded=self.degraded,
        )

    def search(self, query: str, *, limit: int | None = None) -> SearchOutcome:
        """执行单条查询（Agent 自主生成检索词时使用）。"""
        limit = limit or self._max_results
        collector = getattr(self._port, "collector", None)
        search_fn = getattr(collector, "search", None)
        if callable(search_fn):
            try:
                docs = search_fn(query, max_results=limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SearchService.search 失败 | query=%s | err=%s", query, exc)
                return SearchOutcome(docs=[], query=query, provider=self.provider_name,
                                     degraded=True, error=str(exc))
            return SearchOutcome(docs=docs, query=query, provider=self.provider_name,
                                 degraded=self.degraded)

        provider = getattr(self._port, "provider", None)
        search_fn = getattr(provider, "search", None)
        if callable(search_fn):
            try:
                docs = search_fn(query, max_results=limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SearchService.search 失败 | query=%s | err=%s", query, exc)
                return SearchOutcome(docs=[], query=query, provider=self.provider_name,
                                     degraded=True, error=str(exc))
            return SearchOutcome(docs=docs, query=query, provider=self.provider_name,
                                 degraded=self.degraded)

        return SearchOutcome(docs=[], query=query, provider=self.provider_name,
                             degraded=True, error="search port has no search method")

    def supplemental(self, queries: list[str], *, limit: int = 8) -> SearchOutcome:
        """针对 Critic 缺口执行定向补充检索。"""
        clean = [q.strip() for q in queries if q and q.strip()]
        if not clean:
            return SearchOutcome(docs=[], provider=self.provider_name, degraded=self.degraded)
        try:
            docs = self._port.collect_supplemental(  # type: ignore[attr-defined]
                clean, max_results=limit
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearchService.supplemental 失败 | err=%s", exc)
            return SearchOutcome(docs=[], query="；".join(clean), provider=self.provider_name,
                                 degraded=True, error=str(exc))
        return SearchOutcome(
            docs=docs,
            query="；".join(clean),
            provider=self.provider_name,
            degraded=self.degraded,
        )


def build_search_service(
    settings: Settings | None = None,
    *,
    collector: SearchProvider | None = None,
    mock_provider: SearchProvider | None = None,
) -> SearchService:
    """按配置构造搜索服务。

    没有 API Key 或真实采集器构造失败时，自动降级为 Mock provider，
    保证离线开发和测试可以跑通完整 Agent 研究链路。
    """
    settings = settings or get_settings()
    if collector is not None:
        port = (
            CollectorSearchAdapter(collector)
            if hasattr(collector, "collect")
            else ProviderSearchAdapter(collector)
        )
        return SearchService(port, provider_name=getattr(collector, "name", "injected"),
                             max_results=settings.search.max_results)

    if mock_provider is not None:
        return SearchService(
            ProviderSearchAdapter(mock_provider),
            provider_name=getattr(mock_provider, "name", "mock"),
            max_results=settings.search.max_results,
            degraded=True,
        )

    search_key = settings.search.api_key.get_secret_value() if settings.search.api_key else ""
    if search_key:
        try:
            real = SearchCollector.from_settings(settings=settings)
            return SearchService(
                CollectorSearchAdapter(real),
                provider_name="collector",
                max_results=settings.search.max_results,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("真实搜索采集器初始化失败，降级为 Mock | err=%s", exc)

    from ..mocks.search import MockSearchProvider

    return SearchService(
        ProviderSearchAdapter(MockSearchProvider()),
        provider_name="mock",
        max_results=settings.search.max_results,
        degraded=True,
    )


__all__ = ["SearchOutcome", "SearchService", "build_search_service", "SearchError"]
