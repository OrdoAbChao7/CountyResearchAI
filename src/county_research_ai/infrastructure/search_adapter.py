from __future__ import annotations

from datetime import date

from ..domain.modes import ResearchMode
from ..domain.research_contracts import QuestionSlot
from ..models import RawDoc
from ..search.query_engine import QueryEngine
from ..search.region_relevance import filter_documents_for_region


def _year_token(target_years: list[str] | None) -> str:
    years = [year for year in (target_years or []) if str(year).strip()]
    if not years:
        return ""
    if len(years) == 1:
        return f"{years[0]}年"
    return f"{years[0]}-{years[-1]}年"


class CollectorSearchAdapter:
    """将已有 Collector 暴露为 SearchPort。"""

    def __init__(self, collector) -> None:
        self.collector = collector

    def collect(
        self,
        county: str,
        focus: str,
        max_results: int,
        *,
        mode: ResearchMode,
        date_start: date | None = None,
        date_end: date | None = None,
        target_years: list[str] | None = None,
        question_slots: list[QuestionSlot] | None = None,
    ) -> list[RawDoc]:
        kwargs: dict[str, object] = {"mode": mode}
        if date_start is not None:
            kwargs["date_start"] = date_start
        if date_end is not None:
            kwargs["date_end"] = date_end
        if target_years:
            kwargs["target_years"] = target_years
        if question_slots:
            kwargs["question_slots"] = question_slots
        return self.collector.collect(county, focus, max_results, **kwargs)

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
        self,
        county: str,
        focus: str,
        max_results: int,
        *,
        mode: ResearchMode,
        date_start: date | None = None,
        date_end: date | None = None,
        target_years: list[str] | None = None,
        question_slots: list[QuestionSlot] | None = None,
    ) -> list[RawDoc]:
        if question_slots:
            engine = QueryEngine()
            spec = engine.generate_research_spec(
                county, focus, mode, target_years=target_years, question_slots=question_slots,
            )
            queries = [item.query for item in engine.generate_contract_queries(spec)]
            return list(filter_documents_for_region(
                self.collect_supplemental(queries, max_results=max_results), county,
            ).kept)

        year_token = _year_token(target_years)
        queries = [
            f"{county} {focus or '产业'} 产业 发展",
            f"{county} {focus or '产业'} 产值 企业",
            f"{county} 产业 园区 规划",
        ]
        if year_token:
            queries = [f"{county} {year_token} {query[len(county):].strip()}" for query in queries]
        by_url: dict[str, RawDoc] = {}
        without_url: list[RawDoc] = []
        for query in queries:
            for doc in self.provider.search(query, max_results=max_results):
                if not doc.url:
                    without_url.append(doc)
                elif doc.url not in by_url:
                    by_url[doc.url] = doc
        docs = (list(by_url.values()) + without_url)[:max_results]
        return list(filter_documents_for_region(docs, county).kept)

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

