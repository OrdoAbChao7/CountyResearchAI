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

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _TimeoutError

from ..config import Settings, get_settings
from ..exceptions import SearchError
from ..models import RawDoc
from .base import SearchProvider
from .content_extractor import (
    calculate_content_fingerprint,
    extract_publish_date,
    normalize_url,
    rerank_documents,
)
from .gov_data import GovDataProvider
from .query_engine import GeneratedQuery, QueryEngine
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
        self._fail_fast = self._settings.pipeline.fail_fast
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

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        """单查询搜索接口。"""
        n = max_results or self._max_results
        tasks: list[tuple[SearchProvider, str]] = []
        if self._web is not None:
            tasks.append((self._web, query))
        if self._gov is not None:
            tasks.append((self._gov, query))
        docs = self._run_tasks(tasks)
        return self._dedup_and_rank(docs, top=n, keywords=[query])

    def collect(
        self,
        county: str,
        focus: str,
        max_results: int = 0,
        *,
        mode: str = "snapshot",
    ) -> list[RawDoc]:
        """主业务采集接口。优先采用动态消歧与 QueryEngine。"""
        n = max_results or self._max_results
        keywords = [kw for kw in [county, focus] if kw]

        tasks: list[tuple[SearchProvider, str]] = []

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
                    tasks.append((self._web, q))
            if self._gov is not None:
                for tpl in self._gov_query_templates:
                    q = tpl.format(county=county, focus=focus or "")
                    tasks.append((self._gov, q))
        else:
            # 采用动态 QueryEngine 与消歧上下文生成多角度检索词
            generated_queries: list[GeneratedQuery] = self._query_engine.generate_research_queries(
                county=county,
                focus=focus,
                mode=mode,
                max_queries=10,
            )
            for gq in generated_queries:
                if gq.target_channel == "gov" and self._gov is not None:
                    tasks.append((self._gov, gq.query))
                elif self._web is not None:
                    tasks.append((self._web, gq.query))

        if not tasks:
            if self._fail_fast:
                raise SearchError("搜索协调器没有任何可用的 provider 任务")
            logger.warning("没有可用的搜索 provider,返回空结果")
            return []

        docs = self._run_tasks(tasks)
        return self._dedup_and_rank(docs, top=n, keywords=keywords, county=county)

    def collect_supplemental(
        self,
        queries: list[str],
        max_results: int = 10,
    ) -> list[RawDoc]:
        """多轮反思补充检索接口。执行针对性查询。"""
        tasks: list[tuple[SearchProvider, str]] = []
        for q in queries:
            if any(k in q for k in ("统计公报", "国民经济", "规划", "政策")) and self._gov is not None:
                tasks.append((self._gov, q))
            elif self._web is not None:
                tasks.append((self._web, q))

        if not tasks:
            return []

        docs = self._run_tasks(tasks)
        return self._dedup_and_rank(docs, top=max_results, keywords=queries)

    def _run_tasks(self, tasks: list[tuple[SearchProvider, str]]) -> list[RawDoc]:
        """并发执行任务。"""
        results: list[RawDoc] = []
        per_task_timeout = max(10.0, float(self._settings.search.timeout) * 1.5)

        def _worker(t: tuple[SearchProvider, str]) -> list[RawDoc]:
            provider, query = t
            name = provider.name
            try:
                out = provider.search(query, max_results=self._max_results)
                return out
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "收集失败(隔离) | provider=%s | query=%s | err=%s",
                    name, query, e,
                )
                return []

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = {pool.submit(_worker, t): t for t in tasks}
            for fut, (prov, query) in futures.items():
                try:
                    chunk = fut.result(timeout=per_task_timeout)
                except _TimeoutError:
                    logger.warning("收集超时 | provider=%s | query=%s", prov.name, query)
                    continue
                except Exception as e:  # noqa: BLE001
                    logger.warning("收集异常 | provider=%s | query=%s | err=%s", prov.name, query, e)
                    continue
                results.extend(chunk)

        if not results and self._fail_fast:
            raise SearchError(
                "所有搜索任务均失败",
                context={
                    "tasks_count": len(tasks),
                    "providers": sorted({p.name for p, _ in tasks}),
                },
            )
        return results

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
            fp = calculate_content_fingerprint(d.content or d.snippet)
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
