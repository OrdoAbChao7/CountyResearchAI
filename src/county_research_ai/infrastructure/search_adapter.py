from __future__ import annotations

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

    def collect_supplemental(
        self, queries: list[str], max_results: int = 10
    ) -> list[RawDoc]:
        if hasattr(self.collector, "collect_supplemental"):
            return self.collector.collect_supplemental(queries, max_results=max_results)
        by_url: dict[str, RawDoc] = {}
        for q in queries:
            if hasattr(self.collector, "search"):
                for doc in self.collector.search(q, max_results=max_results):
                    key = doc.url or doc.title
                    if key and key not in by_url:
                        by_url[key] = doc
        return list(by_url.values())[:max_results]


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

    def collect_supplemental(
        self, queries: list[str], max_results: int = 10
    ) -> list[RawDoc]:
        by_url: dict[str, RawDoc] = {}
        without_url: list[RawDoc] = []
        for query in queries:
            for doc in self.provider.search(query, max_results=max_results):
                if not doc.url:
                    without_url.append(doc)
                elif doc.url not in by_url:
                    by_url[doc.url] = doc
        return (list(by_url.values()) + without_url)[:max_results]

