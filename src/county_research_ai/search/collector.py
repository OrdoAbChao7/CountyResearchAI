"""搜索协调器(Collector)。

职责:
    1. 根据 county + focus + sources.yaml 中的查询模板,批量构造搜索查询;
    2. 并发调用多个 SearchProvider(Web + Gov) 执行查询;
    3. 结果合并、URL 去重、按相关度(标题/摘要含关键词次数)粗排、
       截断到 max_results 返回。

并发策略(MVP 简化,不引入 async):
    - 用 concurrent.futures.ThreadPoolExecutor(max_workers=settings.search.concurrency)
    - 每个 (provider, query) 对是一个任务,有独立超时
    - 单个任务失败不阻断其他任务,记录 warning 并继续

注意:
    不保留任何模拟数据兜底。如果所有 provider 全部失败:
    - fail_fast=False: 返回空列表,上层 pipeline 继续(后续 LLM 阶段会降级提示无数据)
    - fail_fast=True: 抛 SearchError,整个 pipeline 终止
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

from ..config import Settings, get_settings
from ..exceptions import SearchError
from ..models import RawDoc
from .base import SearchProvider
from .gov_data import GovDataProvider
from .web_search import create_provider

logger = logging.getLogger(__name__)


# 默认通用查询模板(与 sources.yaml 一致,MVP 直接内置,不额外解析 yaml)
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


class SearchCollector(SearchProvider):
    """多 Provider + 多 Query 并发协调器。

    作为"超级 provider"实现 SearchProvider,对外暴露统一的 search() 接口;
    内部管理 Web SearchProvider(一个) + GovDataProvider(一个,复用 Web Provider)。

    MVP 简化:不支持多 Web Provider 同时工作(会多花 API 额度),
    根据 settings.search.provider 选一个最佳 Web + 一个 Gov。
    """

    name = "collector"

    def __init__(
        self,
        *,
        web_provider: SearchProvider | None = None,
        gov_provider: SearchProvider | None = None,
        settings: Settings | None = None,
        query_templates: Iterable[str] | None = None,
        gov_query_templates: Iterable[str] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        s = self._settings.search
        self._max_results = s.max_results
        self._concurrency = max(1, s.concurrency)
        self._fail_fast = self._settings.pipeline.fail_fast
        # provider 构造
        self._web: SearchProvider | None = web_provider
        self._gov: SearchProvider | None = gov_provider
        # 若调用方未注入,懒构造(允许构造时失败,便于上层捕获并降级到 Mock)
        if self._web is None:
            self._web = create_provider(settings=self._settings)
        if self._gov is None and self._web is not None:
            try:
                self._gov = GovDataProvider(web_provider=self._web, settings=self._settings)
            except Exception as e:
                logger.warning("GovDataProvider 构造失败,将仅使用 Web 搜索 | err=%s", e)
                self._gov = None
        self._query_templates = list(query_templates or _DEFAULT_QUERY_TEMPLATES)
        self._gov_query_templates = list(gov_query_templates or _DEFAULT_GOV_QUERY_TEMPLATES)

    # ---- 便捷构造接口(供 pipeline 使用) ----

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None
    ) -> "SearchCollector":
        """从 settings 构造;如果 Web Provider 缺少 Key,抛 SearchError 由上层处理。"""
        return cls(settings=settings)

    # ---- SearchProvider 主接口 ----

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        """Collector.search(query) — 主要供直接使用 collector 作 SearchProvider 的场景。

        业务场景下推荐使用 collect(county, focus)。
        """
        n = max_results or self._max_results
        # 直接调用 web 搜索 + gov 搜索各自一次(query 原样传递)
        tasks: list[tuple[SearchProvider, str]] = []
        if self._web is not None:
            tasks.append((self._web, query))
        if self._gov is not None:
            tasks.append((self._gov, query))
        docs = self._run_tasks(tasks)
        return self._dedup_and_rank(docs, top=n, keywords=[query])

    # ---- 业务主接口 ----

    def collect(self, county: str, focus: str, max_results: int = 0) -> list[RawDoc]:
        """根据县名 + 研究方向构造多查询并发采集。

        先把 {county}/{focus} 填进 query_templates,
        再把 Web 查通用、Gov 查政务的查询分别喂给对应 provider,
        最后合并去重粗排。
        """
        n = max_results or self._max_results
        keywords = [county, focus]
        tasks: list[tuple[SearchProvider, str]] = []
        if self._web is not None:
            for tpl in self._query_templates:
                q = tpl.format(county=county, focus=focus)
                tasks.append((self._web, q))
        if self._gov is not None:
            for tpl in self._gov_query_templates:
                q = tpl.format(county=county, focus=focus)
                tasks.append((self._gov, q))

        if not tasks:
            if self._fail_fast:
                raise SearchError("搜索协调器没有任何可用的 provider 任务")
            logger.warning("没有可用的搜索 provider,返回空结果")
            return []

        docs = self._run_tasks(tasks)
        return self._dedup_and_rank(docs, top=n, keywords=keywords)

    # ---- 内部 ----

    def _run_tasks(self, tasks: list[tuple[SearchProvider, str]]) -> list[RawDoc]:
        """线程池并发执行 (provider, query) 任务,失败隔离。"""
        results: list[RawDoc] = []
        per_task_timeout = max(10.0, float(self._settings.search.timeout) * 1.5)

        def _worker(t: tuple[SearchProvider, str]) -> list[RawDoc]:
            provider, query = t
            name = provider.name
            logger.debug("收集任务 | provider=%s | query=%s", name, query)
            try:
                out = provider.search(query, max_results=self._max_results)
                logger.debug("收集完成 | provider=%s | query=%s | n=%d", name, query, len(out))
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
                    logger.warning(
                        "收集超时 | provider=%s | query=%s",
                        prov.name, query,
                    )
                    continue
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "收集异常 | provider=%s | query=%s | err=%s",
                        prov.name, query, e,
                    )
                    continue
                results.extend(chunk)

        # 全部失败且 fail_fast=True,抛错误
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
    ) -> list[RawDoc]:
        """去重(url 为键) + 粗排(标题/摘要命中关键词次数) + 截断到 top。"""
        # 1) URL 去重
        seen: dict[str, RawDoc] = {}
        for d in docs:
            if not d.url:
                key = f"__no_url__{d.title or d.content[:20]}"
            else:
                key = d.url
            # 保留 content 更长的那一条(详情页抓取优先)
            if key in seen and len(seen[key].content) >= len(d.content):
                continue
            seen[key] = d
        deduped = list(seen.values())
        # 2) 粗排:关键词命中次数(标题*2, 摘要*1, url*1)
        pattern = re.compile("|".join(re.escape(kw) for kw in keywords if kw))

        def _score(d: RawDoc) -> int:
            text = f"{d.title} {d.title} {d.snippet} {d.url}"
            return len(pattern.findall(text)) if keywords else 0

        ranked = sorted(deduped, key=_score, reverse=True)
        # 3) 截断
        if top and top < len(ranked):
            ranked = ranked[:top]
        return ranked
