from __future__ import annotations

from collections.abc import Iterable

from ..domain.modes import ResearchMode
from ..models import RawDoc


class CollectorSearchAdapter:
    """将已有 Collector 暴露为 SearchPort。"""

    def __init__(self, collector) -> None:
        self.collector = collector

    def collect(
        self, county: str, focus: str, max_results: int, *, mode: ResearchMode
    ) -> list[RawDoc]:
        return self.collector.collect(county, focus, max_results, mode=mode)


class ProviderSearchAdapter:
    """将旧的单查询 SearchProvider 兼容为统一采集端口。"""

    def __init__(self, provider) -> None:
        self.provider = provider

    def collect(
        self, county: str, focus: str, max_results: int, *, mode: ResearchMode
    ) -> list[RawDoc]:
        queries = [
            f"{county} {focus or '产业'} 产业 发展",
            f"{county} {focus or '产业'} 产值 企业",
            f"{county} 产业 园区 规划",
        ]
        by_url: dict[str, RawDoc] = {}
        without_url: list[RawDoc] = []
        for query in queries:
            for doc in self.provider.search(query, max_results=max_results):
                if not doc.url:
                    without_url.append(doc)
                elif doc.url not in by_url:
                    by_url[doc.url] = doc
        return (list(by_url.values()) + without_url)[:max_results]
