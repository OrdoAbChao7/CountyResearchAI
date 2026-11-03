from __future__ import annotations

from county_research_ai.infrastructure.search_adapter import (
    CollectorSearchAdapter,
    ProviderSearchAdapter,
)
from county_research_ai.models import RawDoc


def test_collector_adapter_delegates_typed_collect_call() -> None:
    class Collector:
        def collect(self, county, focus, max_results, *, mode):
            return [(county, focus, max_results, mode)]

    adapter = CollectorSearchAdapter(Collector())

    assert adapter.collect("巴中", "茶产业", 5, mode="snapshot") == [
        ("巴中", "茶产业", 5, "snapshot")
    ]


def test_provider_adapter_keeps_legacy_search_as_one_port() -> None:
    class Provider:
        def search(self, query, max_results=10):
            return [RawDoc(title=query, url=query, content=query)]

    adapter = ProviderSearchAdapter(Provider())

    docs = adapter.collect("巴中", "茶产业", 5, mode="snapshot")
    assert len(docs) == 3
    assert docs[0].title == "巴中 茶产业 产业 发展"
