"""通用网络搜索 provider 实现。

基于 httpx 调用三家商业搜索 API:
    - TavilySearchProvider   → Tavily REST API(专为 AI 设计,默认首选)
    - SerperSearchProvider   → Serper.dev(基于 Google)
    - BingSearchProvider     → Bing Web Search API

每个 provider 继承 SearchProvider,统一:
    - 构造函数接收 api_key + timeout 等参数(或从 settings.search 读取)
    - search(query, max_results) 返回 list[RawDoc]
    - API 调用失败抛 SearchError(结构化 context,不保留模拟数据兜底)
    - 内部用 tenacity 重试(指数退避)

依赖检查:
    - Tavily/Serper/Bing 均使用 httpx(已在 pyproject 声明)
    - 不依赖各 provider 的 Python SDK,避免额外依赖
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings, get_settings
from ..exceptions import SearchError
from ..models import RawDoc
from .base import SearchProvider

logger = logging.getLogger(__name__)

# ===== 通用工具 =====


def _build_headers(auth_header: str, api_key: str) -> dict[str, str]:
    """统一构造请求头。"""
    return {
        auth_header: api_key,
        "Accept": "application/json",
        "User-Agent": "CountyResearchAI/0.1.0",
    }


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


def _truncate(text: str, max_chars: int) -> str:
    """按字符数截断,末尾追加 ...。"""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


# ===== 1. Tavily =====


class TavilySearchProvider(SearchProvider):
    """Tavily 搜索提供商。

    API 参考: https://docs.tavily.com/docs/tavily-api/rest_api
    POST https://api.tavily.com/search
    body: {api_key, query, search_depth, max_results, include_answer, include_raw_content}
    """

    name = "tavily"
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        settings: Settings | None = None,
        fetch_detail: bool | None = None,
        detail_max_chars: int | None = None,
        timeout: float | None = None,
    ) -> None:
        s = settings or get_settings()
        self._api_key = api_key or s.search.api_key.get_secret_value()
        if not self._api_key:
            raise SearchError(
                "Tavily API Key 未配置",
                context={"hint": "请在 .env 中设置 TAVILY_API_KEY"},
            )
        self._max_results = s.search.max_results
        self._fetch_detail = fetch_detail if fetch_detail is not None else s.search.fetch_detail
        self._detail_max_chars = detail_max_chars or s.search.detail_max_chars
        self._timeout = timeout or float(s.search.timeout)
        self._retry_cfg = s.search.retry
        # search_depth=basic 速度快且免费额度高;advanced 更准但更慢更贵
        self._search_depth = "basic"

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        n = max_results or self._max_results
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": self._search_depth,
            "max_results": n,
            "include_answer": False,
            "include_raw_content": True,
        }

        @retry(
            stop=stop_after_attempt(self._retry_cfg.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry_cfg.backoff_seconds,
                min=self._retry_cfg.backoff_seconds,
                max=self._retry_cfg.backoff_seconds * 10,
            ),
            retry=retry_if_exception_type(SearchError),
            reraise=True,
        )
        def _call() -> dict[str, Any]:
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(self.ENDPOINT, json=payload)
                    if resp.status_code == 429:
                        raise SearchError("Tavily 请求限流(429)", context={"query": query})
                    if resp.status_code == 401:
                        raise SearchError("Tavily API Key 无效(401)", context={"query": query})
                    if resp.status_code >= 400:
                        raise SearchError(
                            f"Tavily HTTP {resp.status_code}",
                            context={"query": query, "body": resp.text[:200]},
                        )
                    data = resp.json()
            except SearchError:
                raise
            except httpx.HTTPError as e:
                raise SearchError(
                    f"Tavily 网络错误: {type(e).__name__}",
                    context={"query": query, "error": str(e)},
                ) from e
            return data

        try:
            data = _call()
        except RetryError as e:
            raise SearchError(
                "Tavily 调用重试耗尽",
                context={"query": query, "attempts": self._retry_cfg.max_attempts, "last_error": str(e)},
            ) from e

        return self._parse_results(data.get("results", []))

    def _parse_results(self, results: list[dict[str, Any]]) -> list[RawDoc]:
        docs: list[RawDoc] = []
        for item in results:
            raw = item.get("raw_content") or ""
            snippet = item.get("snippet", "")
            # 优先用 raw_content(Tavily 全文),退化用 snippet
            content = _truncate(raw or snippet, self._detail_max_chars)
            docs.append(RawDoc(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=snippet,
                content=content,
                source=self.name,
                fetched_at=_utcnow(),
                metadata={
                    "score": item.get("score"),
                    "content_type": item.get("content_type"),
                },
            ))
        return docs


# ===== 2. Serper =====


class SerperSearchProvider(SearchProvider):
    """Serper 搜索提供商(基于 Google)。

    API 参考: https://serper.dev/
    POST https://google.serper.dev/search
    Header: X-API-KEY
    body: {q, num, gl, hl}
    """

    name = "serper"
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        settings: Settings | None = None,
        fetch_detail: bool | None = None,
        detail_max_chars: int | None = None,
        timeout: float | None = None,
    ) -> None:
        s = settings or get_settings()
        self._api_key = api_key or s.search.api_key.get_secret_value()
        if not self._api_key:
            raise SearchError(
                "Serper API Key 未配置",
                context={"hint": "请在 .env 中设置 SERPER_API_KEY"},
            )
        self._max_results = s.search.max_results
        self._fetch_detail = fetch_detail if fetch_detail is not None else s.search.fetch_detail
        self._detail_max_chars = detail_max_chars or s.search.detail_max_chars
        self._timeout = timeout or float(s.search.timeout)
        self._retry_cfg = s.search.retry

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        n = max_results or self._max_results
        headers = _build_headers("X-API-KEY", self._api_key)
        payload = {"q": query, "num": n, "gl": "cn", "hl": "zh-cn"}

        @retry(
            stop=stop_after_attempt(self._retry_cfg.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry_cfg.backoff_seconds,
                min=self._retry_cfg.backoff_seconds,
                max=self._retry_cfg.backoff_seconds * 10,
            ),
            retry=retry_if_exception_type(SearchError),
            reraise=True,
        )
        def _call() -> dict[str, Any]:
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(self.ENDPOINT, headers=headers, json=payload)
                    if resp.status_code == 429:
                        raise SearchError("Serper 请求限流(429)", context={"query": query})
                    if resp.status_code in (401, 403):
                        raise SearchError("Serper API Key 无效", context={"query": query})
                    if resp.status_code >= 400:
                        raise SearchError(
                            f"Serper HTTP {resp.status_code}",
                            context={"query": query, "body": resp.text[:200]},
                        )
                    return resp.json()
            except SearchError:
                raise
            except httpx.HTTPError as e:
                raise SearchError(
                    f"Serper 网络错误: {type(e).__name__}",
                    context={"query": query, "error": str(e)},
                ) from e

        try:
            data = _call()
        except RetryError as e:
            raise SearchError(
                "Serper 调用重试耗尽",
                context={"query": query, "attempts": self._retry_cfg.max_attempts, "last_error": str(e)},
            ) from e

        organic = data.get("organic", [])
        docs: list[RawDoc] = []
        for item in organic:
            snippet = item.get("snippet", "")
            content = _truncate(snippet, self._detail_max_chars) if self._fetch_detail else ""
            docs.append(RawDoc(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=snippet,
                content=content,
                source=self.name,
                fetched_at=_utcnow(),
                metadata={
                    "position": item.get("position"),
                    "date": item.get("date"),
                },
            ))
        return docs


# ===== 3. Bing =====


class BingSearchProvider(SearchProvider):
    """Bing Web Search 提供商。

    API 参考: https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search
    GET https://api.bing.microsoft.com/v7.0/search?q=...&mkt=zh-CN&count=N
    Header: Ocp-Apim-Subscription-Key
    """

    name = "bing"
    ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        settings: Settings | None = None,
        fetch_detail: bool | None = None,
        detail_max_chars: int | None = None,
        timeout: float | None = None,
    ) -> None:
        s = settings or get_settings()
        self._api_key = api_key or s.search.api_key.get_secret_value()
        if not self._api_key:
            raise SearchError(
                "Bing API Key 未配置",
                context={"hint": "请在 .env 中设置 BING_API_KEY"},
            )
        self._max_results = s.search.max_results
        self._fetch_detail = fetch_detail if fetch_detail is not None else s.search.fetch_detail
        self._detail_max_chars = detail_max_chars or s.search.detail_max_chars
        self._timeout = timeout or float(s.search.timeout)
        self._retry_cfg = s.search.retry

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        n = max_results or self._max_results
        headers = _build_headers("Ocp-Apim-Subscription-Key", self._api_key)
        params = {
            "q": query,
            "mkt": "zh-CN",
            "count": n,
            "setLang": "zh-CN",
            "textDecorations": "false",
            "textFormat": "raw",
        }

        @retry(
            stop=stop_after_attempt(self._retry_cfg.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry_cfg.backoff_seconds,
                min=self._retry_cfg.backoff_seconds,
                max=self._retry_cfg.backoff_seconds * 10,
            ),
            retry=retry_if_exception_type(SearchError),
            reraise=True,
        )
        def _call() -> dict[str, Any]:
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(self.ENDPOINT, headers=headers, params=params)
                    if resp.status_code == 429:
                        raise SearchError("Bing 请求限流(429)", context={"query": query})
                    if resp.status_code == 401:
                        raise SearchError("Bing API Key 无效(401)", context={"query": query})
                    if resp.status_code >= 400:
                        raise SearchError(
                            f"Bing HTTP {resp.status_code}",
                            context={"query": query, "body": resp.text[:200]},
                        )
                    return resp.json()
            except SearchError:
                raise
            except httpx.HTTPError as e:
                raise SearchError(
                    f"Bing 网络错误: {type(e).__name__}",
                    context={"query": query, "error": str(e)},
                ) from e

        try:
            data = _call()
        except RetryError as e:
            raise SearchError(
                "Bing 调用重试耗尽",
                context={"query": query, "attempts": self._retry_cfg.max_attempts, "last_error": str(e)},
            ) from e

        web_pages = data.get("webPages", {}).get("value", [])
        docs: list[RawDoc] = []
        for item in web_pages:
            snippet = item.get("snippet", "")
            content = _truncate(snippet, self._detail_max_chars) if self._fetch_detail else ""
            docs.append(RawDoc(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=snippet,
                content=content,
                source=self.name,
                fetched_at=_utcnow(),
                metadata={
                    "id": item.get("id"),
                    "displayUrl": item.get("displayUrl"),
                    "datePublished": item.get("datePublished"),
                },
            ))
        return docs


# ===== Provider 工厂 =====


PROVIDER_CLASSES: dict[str, type[SearchProvider]] = {
    "tavily": TavilySearchProvider,
    "serper": SerperSearchProvider,
    "bing": BingSearchProvider,
}


def create_provider(
    provider: str | None = None,
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> SearchProvider:
    """按 provider 名称构造实例的工厂函数。

    Args:
        provider: 名称(tavily/serper/bing);None 则从 settings.search.provider 读取
        api_key: 可显式传入;None 则从 settings.search.api_key 读取
        settings: 自定义 settings 注入(测试用)

    Returns:
        构造好的 SearchProvider 实例

    Raises:
        SearchError: provider 名称无效或 API Key 未配置
    """
    s = settings or get_settings()
    name = (provider or s.search.provider).lower()
    if name not in PROVIDER_CLASSES:
        raise SearchError(
            f"未知的搜索提供商: {name}",
            context={"available": sorted(PROVIDER_CLASSES.keys())},
        )
    cls = PROVIDER_CLASSES[name]
    return cls(api_key=api_key, settings=s)
