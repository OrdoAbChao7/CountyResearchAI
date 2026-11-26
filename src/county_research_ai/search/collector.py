"""搜索协调器(Collector)。

职责:
    1. 根据 county + focus，结合 QueryEngine 与消歧结果动态生成多维度搜索查询；
    2. 支持传统模版兼容与多轮反思补充检索；
    3. 并发调用多个 SearchProvider(Web + Gov) 执行查询；
    4. 结果合并、URL 规范化去重、跨站重复识别、混合相关度重排、
       截断到 max_results 返回。

并发策略:
    - ThreadPoolExecutor(max_workers=settings.search.concurrency)
    - 单个任务失败不阻断其他任务，记录 warning 并继续。
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as _TimeoutError
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ..config import Settings, get_settings
from ..domain.research_contracts import QuestionSlot
from ..exceptions import SearchError
from ..models import RawDoc
from ..observability import emit
from .adaptive_retrieval import (
    AdaptiveCollectionResult,
    AdaptiveQueryPlan,
    AdaptiveRetrievalController,
    RankedDocument,
    RetrievalStopReason,
    build_adaptive_query_plan,
    rank_documents_for_slot,
)
from .base import SearchProvider
from .content_extractor import (
    calculate_content_fingerprint,
    extract_publish_date,
    normalize_url,
    rerank_documents,
)
from .gov_data import GovDataProvider
from .pdf_extractor import extract_pdf_text_bytes, fetch_pdf_bytes, is_pdf_document
from .query_engine import GeneratedQuery, QueryEngine
from .region_relevance import filter_documents_for_region
from .request_history import (
    SearchDocumentRecord,
    SearchExecution,
    SearchRequestHistory,
    SearchRequestKey,
    current_search_history,
    normalize_query,
)
from .web_search import create_provider

logger = logging.getLogger(__name__)


# 默认通用查询模板(保持历史兼容)
_DEFAULT_QUERY_TEMPLATES = [
    "{county} {focus} 产业 发展现状",
    "{county} {focus} 产值 企业 龙头",
    "{county} {focus} 政策 规划 十四五",
    "{county} 产业 园区 招商引资",
]

_DEFAULT_GOV_QUERY_TEMPLATES = [
    "{county} 统计公报 国民经济",
    "{county} 十四五 产业 规划",
    "{county} 特色产业 优势产业",
]

_HISTORICAL_QUERY_TEMPLATES = [
    "{county} 历史 产业 发展",
    "{county} 地方志 工业 农业 商贸",
    "{county} 主导产业 历史",
    "{county} 统计公报 财政收入 人口",
    "{county} 人口流出 人才流失",
    "{county} 产业衰退 企业倒闭",
    "{county} 资源枯竭 环保整治",
    "{county} 龙头企业 产业园区",
    "{county} 县域经济 转型",
    "{county} 政府工作报告 产业",
]

_LONG_HISTORY_QUERY_TEMPLATES = [
    "{county} 建县 历史 沿革",
    "{county} 县志 地方志",
    "{county} 地方志 商贸 农业",
    "{county} 历史 交通 驿道 水运",
    "{county} 人口 迁徙",
    "{county} 近代 工业 商业",
    "{county} 计划经济 国营 工厂",
    "{county} 改革开放 产业变化",
    "{county} 行政区划 变迁",
    "{county} 历史 兴衰 原因",
]


def _document_records(docs: Iterable[RawDoc]) -> list[SearchDocumentRecord]:
    """Describe provider results without claiming their content was parsed."""
    records: list[SearchDocumentRecord] = []
    for doc in docs:
        content = doc.content or ""
        snippet = doc.snippet or ""
        text = content or snippet
        text_origin: Literal["content", "snippet", "none"] = (
            "content" if content else ("snippet" if snippet else "none")
        )
        content_type = str(doc.metadata.get("content_type") or "").strip()
        is_pdf = is_pdf_document(doc.url, content_type)
        parse_status: Literal[
            "text", "pdf_parsed", "pdf_text_from_provider", "pdf_not_parsed", "no_text"
        ]
        if is_pdf and doc.metadata.get("pdf_parsed_by_app") and content:
            parse_status, parse_reason = "pdf_parsed", ""
        elif is_pdf and content:
            # Provider body text exists, but the app did not parse the PDF bytes.
            parse_status, parse_reason = "pdf_text_from_provider", "pdf_body_not_parsed_by_app"
        elif is_pdf:
            reason = str(doc.metadata.get("pdf_parse_reason") or "pdf_content_not_supported")
            parse_status, parse_reason = "pdf_not_parsed", reason
        elif content:
            parse_status, parse_reason = "text", ""
        else:
            parse_status, parse_reason = "no_text", "no_text_content"
        records.append(SearchDocumentRecord(
            url=doc.url,
            title=doc.title,
            content_type=content_type,
            content_chars=len(content),
            snippet_chars=len(snippet),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            text_origin=text_origin,
            parse_status=parse_status,
            parse_reason=parse_reason,
        ))
    return records


@dataclass(frozen=True)
class _SearchTask:
    provider: SearchProvider
    backend: SearchProvider
    query: str
    max_results: int

    @property
    def request_key(self) -> SearchRequestKey:
        return id(self.backend), self.query, self.max_results

    @property
    def route_key(self) -> SearchRequestKey:
        return id(self.provider), self.query, self.max_results

    def process(self, raw: list[RawDoc]) -> list[RawDoc]:
        if isinstance(self.provider, GovDataProvider) and self.provider is not self.backend:
            # Enrichment can mutate documents shared with the Web route.
            docs = [doc.model_copy(deep=True) for doc in raw]
            return self.provider.process_search_results(docs, self.max_results)
        return raw


class SearchCollector(SearchProvider):
    """多 Provider + 多 Query 并发协调器（支持动态检索与反思补充）。"""

    name = "collector"

    def __init__(
        self,
        *,
        web_provider: SearchProvider | None = None,
        gov_provider: SearchProvider | None = None,
        settings: Settings | None = None,
        query_templates: Iterable[str] | None = None,
        gov_query_templates: Iterable[str] | None = None,
        query_engine: QueryEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        s = self._settings.search
        self._max_results = s.max_results
        self._concurrency = max(1, s.concurrency)
        self._fail_fast = self._settings.runtime.fail_fast
        self._web: SearchProvider | None = web_provider
        self._gov: SearchProvider | None = gov_provider
        if self._web is None:
            self._web = create_provider(settings=self._settings)
        if self._gov is None and self._web is not None:
            try:
                self._gov = GovDataProvider(web_provider=self._web, settings=self._settings)
            except Exception as e:
                logger.warning("GovDataProvider 构造失败,将仅使用 Web 搜索 | err=%s", e)
                self._gov = None

        self._custom_templates = query_templates is not None
        self._custom_gov_templates = gov_query_templates is not None
        self._query_templates = list(query_templates or _DEFAULT_QUERY_TEMPLATES)
        self._gov_query_templates = list(gov_query_templates or _DEFAULT_GOV_QUERY_TEMPLATES)
        self._query_engine = query_engine or QueryEngine()

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None
    ) -> SearchCollector:
        return cls(settings=settings)

    def _search_task(self, provider: SearchProvider, query: str) -> _SearchTask:
        backend, limit = provider, self._max_results
        # Only unwrap the built-in government route. Custom providers own their searches.
        if type(provider) is GovDataProvider:
            backend, limit = provider.search_backend(limit)
        return _SearchTask(provider, backend, normalize_query(query), limit)

    def _adaptive_task(self, query: GeneratedQuery) -> _SearchTask | None:
        provider = self._gov if query.target_channel == "gov" and self._gov is not None else self._web
        if provider is None or not query.query.strip():
            return None
        return self._search_task(provider, query.query)

    def adaptive_request_keys(
        self, query: GeneratedQuery
    ) -> tuple[SearchRequestKey, SearchRequestKey] | None:
        task = self._adaptive_task(query)
        return (task.request_key, task.route_key) if task is not None else None

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        """单查询搜索接口。"""
        n = max_results or self._max_results
        tasks = [self._search_task(p, query) for p in (self._web, self._gov) if p is not None]
        docs = self._collect_unranked(tasks)
        return self._dedup_and_rank(docs, top=n, keywords=[query])

    def collect(
        self,
        county: str,
        focus: str,
        max_results: int = 0,
        *,
        mode: str = "snapshot",
        date_start: date | None = None,
        date_end: date | None = None,
        target_years: list[str] | None = None,
        question_slots: list[QuestionSlot] | None = None,
    ) -> list[RawDoc]:
        """主业务采集接口。优先采用动态消歧与 QueryEngine。

        ``date_start``/``date_end`` are accepted so every layer receives the
        contract window. They are deliberately not used to filter search
        results by publication date: a 2025 bulletin may report 2024 data.
        """
        n = max_results or self._max_results
        if question_slots:
            spec = self._query_engine.generate_research_spec(
                county, focus, mode, target_years=target_years, question_slots=question_slots,
            )
            plan = build_adaptive_query_plan(spec, self._query_engine, max_queries=None)
            emit("retrieval.round.started", stage="collect", payload={
                "round": 1,
                "queries": len(plan.queries),
                "query_texts": [query.query for query in plan.queries],
                "query_slot_ids": [query.slot_id for query in plan.queries],
                "supplemental": False,
            })
            result = self.collect_adaptive(plan, max_results=n)
            emit("retrieval.round.completed", stage="collect", payload={
                "round": 1, "documents": len(result.documents), "usage": result.usage,
            })
            return list(result.documents)

        keywords = [kw for kw in [county, focus] if kw]
        tasks: list[_SearchTask] = []

        # 若调用方显式注入了自定义模板，保持历史模板逻辑
        if self._custom_templates or self._custom_gov_templates:
            if mode == "rise-fall":
                web_templates = _HISTORICAL_QUERY_TEMPLATES
            elif mode == "long-history":
                web_templates = _LONG_HISTORY_QUERY_TEMPLATES
            else:
                web_templates = self._query_templates

            if self._web is not None:
                for tpl in web_templates:
                    q = tpl.format(county=county, focus=focus or "")
                    tasks.append(self._search_task(self._web, q))
            if self._gov is not None:
                for tpl in self._gov_query_templates:
                    q = tpl.format(county=county, focus=focus or "")
                    tasks.append(self._search_task(self._gov, q))
        else:
            # 采用动态 QueryEngine 与消歧上下文生成多角度检索词
            generated_queries: list[GeneratedQuery] = self._query_engine.generate_research_queries(
                county=county,
                focus=focus,
                mode=mode,
                max_queries=10,
                target_years=target_years,
            )
            for gq in generated_queries:
                task = self._adaptive_task(gq)
                if task is not None:
                    tasks.append(task)

        if not tasks:
            if self._fail_fast:
                raise SearchError("搜索协调器没有任何可用的 provider 任务")
            logger.warning("没有可用的搜索 provider,返回空结果")
            return []

        raw_docs = self._collect_unranked(tasks)
        docs = self._filter_region_documents(raw_docs, county)
        return self._dedup_and_rank(docs, top=n, keywords=keywords, county=county)

    def collect_supplemental(
        self,
        queries: list[str],
        max_results: int = 10,
        *,
        county: str = "",
    ) -> list[RawDoc]:
        """多轮反思补充检索接口。执行针对性查询。"""
        tasks: list[_SearchTask] = []
        for q in queries:
            if any(k in q for k in ("统计公报", "国民经济", "规划", "政策")) and self._gov is not None:
                tasks.append(self._search_task(self._gov, q))
            elif self._web is not None:
                tasks.append(self._search_task(self._web, q))

        raw_docs = self._collect_unranked(tasks)
        docs = self._filter_region_documents(raw_docs, county)
        return self._dedup_and_rank(docs, top=max_results, keywords=queries)

    def collect_adaptive(
        self,
        plan: AdaptiveQueryPlan,
        *,
        controller: AdaptiveRetrievalController | None = None,
        max_results: int = 0,
    ) -> AdaptiveCollectionResult:
        """Execute a bounded plan while returning explicit search/fetch usage."""
        history = controller.search_history if controller else (current_search_history() or SearchRequestHistory())
        planned: list[tuple[GeneratedQuery, _SearchTask]] = []
        skipped: list[tuple[GeneratedQuery, _SearchTask | None]] = []
        known_requests = set(history.responses)
        for generated in plan.queries:
            task = self._adaptive_task(generated)
            if task is not None and history.can_use(task.request_key, task.route_key, generated.slot_id):
                planned.append((generated, task))
            else:
                skipped.append((generated, task))
        tasks = [task for _, task in planned]
        new_routes = {task.route_key for task in tasks} - history.route_results.keys()
        # The planner already reserved the new backend requests.
        try:
            by_route, search_count = self._run_tasks(tasks, history=history)
        finally:
            self._record_contract_queries(plan, history, known_requests, planned, skipped)
        if not planned:
            return AdaptiveCollectionResult(
                documents=(),
                usage={"search_queries": 0, "fetched_documents": 0},
                stop_reason=RetrievalStopReason.NO_GAP_QUERY,
            )
        history.used_queries.update((task.route_key, query.slot_id) for query, task in planned)
        fetched = sum(len(by_route[key]) for key in new_routes if key in by_route)
        if controller:
            controller.record_fetches(fetched)
        region_filter = filter_documents_for_region(
            (doc for docs in by_route.values() for doc in docs), plan.spec.region_name,
        )
        if region_filter.dropped:
            logger.info(
                "区域相关性过滤 | county=%s | kept=%d | dropped=%d | dropped_urls=%s",
                plan.spec.region_name,
                len(region_filter.kept),
                len(region_filter.dropped),
                [doc.url for doc, _ in region_filter.dropped][:5],
            )
        kept = {id(doc) for doc in region_filter.kept}
        region_docs = {key: [doc for doc in docs if id(doc) in kept] for key, docs in by_route.items()}
        limit = max_results or self._max_results
        if plan.spec.question_slots:
            ranked = self._rank_adaptive_documents(planned, region_docs, plan.spec.question_slots)
        else:
            ranked = self._dedup_and_rank(
                list(region_filter.kept), top=limit, keywords=[query.query for query, _ in planned],
            )
        return AdaptiveCollectionResult(
            documents=tuple(ranked[:limit]),
            usage={
                "search_queries": search_count,
                "fetched_documents": fetched,
                "region_filtered_documents": len(region_filter.dropped),
                "returned_documents": len(ranked[:limit]),
            },
        )

    @staticmethod
    def _record_contract_queries(
        plan: AdaptiveQueryPlan,
        history: SearchRequestHistory,
        known_requests: set[SearchRequestKey],
        planned: list[tuple[GeneratedQuery, _SearchTask]],
        skipped: list[tuple[GeneratedQuery, _SearchTask | None]],
    ) -> None:
        slot_ids = {slot.slot_id for slot in plan.spec.question_slots if slot.is_contract_question}
        executions: list[SearchExecution] = []
        for query, task in planned:
            seen = task.request_key in known_requests
            known_requests.add(task.request_key)
            if query.slot_id not in slot_ids:
                continue
            docs = history.route_results.get(task.route_key)
            if task.request_key not in history.responses:
                request, status, reason = "skipped", "skipped", "request_not_recorded"
            elif docs is None:
                request = "reused" if seen else "executed"
                status = "failed"
                reason = "provider_failed" if history.responses[task.request_key] is None else "route_failed"
            else:
                request = "reused" if seen else "executed"
                status, reason = ("results" if docs else "empty"), ""
            executions.append(SearchExecution(
                slot_id=query.slot_id, round=plan.round_number, query=task.query, provider=task.provider.name,
                request=request, status=status, reason=reason, returned_documents=len(docs or ()),
                documents=_document_records(docs or ()),
            ))
        for query, task in skipped:
            if query.slot_id in slot_ids:
                executions.append(SearchExecution(
                    slot_id=query.slot_id, round=plan.round_number, query=query.query,
                    provider=task.provider.name if task is not None else query.target_channel,
                    request="skipped", status="skipped",
                    reason="already_used_or_unusable" if task is not None else "no_provider_route",
                ))
        if executions:
            history.executions.extend(executions)
            emit(
                "retrieval.queries.completed",
                stage="collect" if plan.round_number == 1 else "analyze",
                payload={"round": plan.round_number, "executions": [item.model_dump() for item in executions]},
            )

    @staticmethod
    def _rank_adaptive_documents(
        planned: list[tuple[GeneratedQuery, _SearchTask]],
        documents_by_route: dict[SearchRequestKey, list[RawDoc]],
        question_slots: list[QuestionSlot],
    ) -> list[RawDoc]:
        slots = {slot.slot_id: slot for slot in question_slots}
        ranked_by_url: dict[str, RankedDocument] = {}
        for query, task in planned:
            # A period query without a slot can serve any question in the spec.
            ranking_slots = (slots[query.slot_id],) if query.slot_id in slots else question_slots
            for slot in ranking_slots:
                for item in rank_documents_for_slot(
                    documents_by_route.get(task.route_key, []), slot, query=query.query,
                ):
                    key = normalize_url(item.document.url) or item.fingerprint or item.document.title
                    current = ranked_by_url.get(key)
                    if current is None or item.score > current.score:
                        ranked_by_url[key] = item
        ranked = sorted(ranked_by_url.values(), key=lambda item: (-item.score, item.document.url, item.document.title))
        seen_fingerprints: set[str] = set()
        results: list[RawDoc] = []
        for item in ranked:
            if item.fingerprint and item.fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(item.fingerprint)
            results.append(item.document)
        return results

    @staticmethod
    def _filter_region_documents(
        docs: list[RawDoc], county: str
    ) -> list[RawDoc]:
        """Drop results that positively belong to another region or to the nation."""
        if not county:
            return docs
        result = filter_documents_for_region(docs, county)
        if result.dropped:
            verdicts: dict[str, int] = {}
            for _, assessment in result.dropped:
                verdicts[assessment.verdict.value] = (
                    verdicts.get(assessment.verdict.value, 0) + 1
                )
            emit(
                "retrieval.region_filtered",
                stage="collect",
                payload={
                    "county": county,
                    "kept": len(result.kept),
                    "dropped": len(result.dropped),
                    "verdicts": verdicts,
                },
            )
            logger.info(
                "区域相关性过滤 | county=%s | kept=%d | dropped=%d | dropped_urls=%s",
                county,
                len(result.kept),
                len(result.dropped),
                [doc.url for doc, _ in result.dropped][:5],
            )
        return list(result.kept)

    def _collect_unranked(self, tasks: list[_SearchTask]) -> list[RawDoc]:
        history = current_search_history() or SearchRequestHistory()
        by_route, _ = self._run_tasks(tasks, history=history)
        history.used_queries.update((key, "") for key in by_route)
        return [doc for docs in by_route.values() for doc in docs]

    def _wait_for_results(
        self, futures: dict[SearchRequestKey, Future[list[RawDoc]]], *, stage: str,
    ) -> dict[SearchRequestKey, list[RawDoc] | None]:
        timeout = max(10.0, float(self._settings.search.timeout) * 1.5)
        results: dict[SearchRequestKey, list[RawDoc] | None] = {}
        for key, future in futures.items():
            try:
                results[key] = future.result(timeout=timeout)
            except _TimeoutError:
                logger.warning("收集超时 | stage=%s | query=%s", stage, key[1])
                results[key] = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("收集异常 | stage=%s | query=%s | err=%s", stage, key[1], exc)
                results[key] = None
        return results

    def _run_tasks(
        self, tasks: list[_SearchTask], *, history: SearchRequestHistory,
    ) -> tuple[dict[SearchRequestKey, list[RawDoc]], int]:
        """Fetch each backend response once and isolate each route's processing."""
        routes = {task.route_key: task for task in tasks if task.query}
        if not routes:
            return {}, 0
        requests = {
            task.request_key: task for task in routes.values() if task.request_key not in history.responses
        }
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            searches = {
                key: pool.submit(task.backend.search, task.query, max_results=task.max_results)
                for key, task in requests.items()
            }
            fetched = self._wait_for_results(searches, stage="search")
            if self._settings.search.fetch_detail:
                fetched = {
                    key: self._enrich_pdf_documents(docs) if docs is not None else None
                    for key, docs in fetched.items()
                }
            history.responses.update(fetched)
            # Preserve successful Web results even if Gov filtering/enrichment times out.
            processing: dict[SearchRequestKey, Future[list[RawDoc]]] = {}
            for key, task in routes.items():
                if key in history.route_results:
                    continue
                raw = history.responses[task.request_key]
                if raw and task.provider is not task.backend:
                    processing[key] = pool.submit(task.process, raw)
                else:
                    history.route_results[key] = raw
            history.route_results.update(self._wait_for_results(processing, stage="gov"))

        # Callers may normalize URLs or clean the content in place.
        results = {
            key: [doc.model_copy(deep=True) for doc in docs]
            for key in routes if (docs := history.route_results[key]) is not None
        }
        failed_routes = sum(history.route_results.get(key) is None for key in routes)
        # An empty result is not a failure: only a batch where every route
        # failed aborts the job.
        if self._fail_fast and not results and failed_routes == len(routes):
            raise SearchError(
                "所有搜索任务均失败",
                context={
                    "tasks_count": len(routes),
                    "failed_tasks": failed_routes,
                    "providers": sorted({task.provider.name for task in routes.values()}),
                },
            )
        return results, len(requests)

    def _enrich_pdf_documents(self, docs: list[RawDoc]) -> list[RawDoc]:
        """Fetch and parse bodyless PDF results when ``search.fetch_detail`` is enabled."""
        max_chars = int(self._settings.search.detail_max_chars or 0)
        timeout = float(self._settings.search.timeout or 20.0)
        enriched: list[RawDoc] = []
        for doc in docs:
            ctype = str(doc.metadata.get("content_type") or "")
            if doc.content or not is_pdf_document(doc.url, ctype):
                enriched.append(doc)
                continue
            try:
                raw_bytes, resp_ctype = fetch_pdf_bytes(doc.url, timeout=timeout)
                text, pages = extract_pdf_text_bytes(raw_bytes, max_chars=max_chars)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PDF 正文抓取/解析失败 | url=%s | err=%s", doc.url, exc)
                enriched.append(
                    doc.model_copy(
                        update={
                            "metadata": {
                                **doc.metadata,
                                "pdf_parse_reason": "pdf_fetch_or_parse_failed",
                            }
                        }
                    )
                )
                continue
            if not text:
                enriched.append(
                    doc.model_copy(
                        update={
                            "metadata": {
                                **doc.metadata,
                                "content_type": ctype or resp_ctype or "application/pdf",
                                "pdf_pages": pages,
                                "pdf_parse_reason": "pdf_empty_or_scanned",
                            }
                        }
                    )
                )
                continue
            enriched.append(
                doc.model_copy(
                    update={
                        "content": text,
                        "metadata": {
                            **doc.metadata,
                            "content_type": ctype or resp_ctype or "application/pdf",
                            "detail_fetched": True,
                            "pdf_parsed_by_app": True,
                            "pdf_pages": pages,
                        },
                    }
                )
            )
        return enriched

    def _dedup_and_rank(
        self,
        docs: list[RawDoc],
        *,
        top: int,
        keywords: list[str],
        county: str = "",
    ) -> list[RawDoc]:
        """去重 + 规范化 + 排序。

        兼顾测试直接通过类方法调用：SearchCollector._dedup_and_rank(SearchCollector, docs, ...)
        """
        seen: dict[str, RawDoc] = {}
        seen_fingerprints: set[str] = set()

        for d in docs:
            # 规范化 URL 与提取时间
            if d.url:
                norm_u = normalize_url(d.url)
                d.url = norm_u
                if not d.published_at:
                    d.published_at = extract_publish_date(
                        f"{d.title} {d.snippet} {d.content[:500]}", norm_u
                    )
                key = norm_u
            else:
                key = f"__no_url__{d.title or d.content[:20]}"

            # 跨站内容重复指纹
            fp = calculate_content_fingerprint(d.content or d.snippet, title=d.title)
            if fp and fp in seen_fingerprints and key not in seen:
                continue

            # 保留正文更长的一条
            if key in seen and len(seen[key].content) >= len(d.content):
                continue

            seen[key] = d
            if fp:
                seen_fingerprints.add(fp)

        deduped = list(seen.values())

        # 排序：使用混合相关度重排
        ranked = rerank_documents(deduped, keywords=keywords, county=county, top_k=top)
        return ranked
