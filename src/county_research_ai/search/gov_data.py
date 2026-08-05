"""政府公开数据 provider。

策略(两阶段):
    阶段 1 - 搜索:复用已有的 Web SearchProvider(Tavily/Serper/Bing),
              使用 sources.yaml 中 gov_sources.query_templates 生成政府相关查询;
    阶段 2 - 过滤 + 抓取:仅保留命中 gov_sources.domains 白名单的结果;
              如果 settings.search.fetch_detail=True,用 httpx + BeautifulSoup
              抓取详情页正文(HTML→文本),并按 detail_max_chars 截断。

白名单域名匹配规则:
    - 精确域名匹配(url_domain == domain)
    - 子域名匹配(*.example.com 匹配 a.b.example.com / example.com)
    - 可选 path_keywords 路径关键词过滤(仅抓官网专题页,避免导航页/新闻列表)

依赖检查:
    - 复用 SearchProvider(已在 web_search.py)
    - BeautifulSoup 延迟导入:未装则抛结构化 SearchError 提示 pip install beautifulsoup4
      (已在 pyproject.dependencies 声明)
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

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
from .web_search import create_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GovDomain:
    """白名单域名项。"""
    name: str
    domain: str = ""            # 精确域名(如 stats.gov.cn)
    pattern: str = ""           # Glob 模式(如 *.gov.cn)
    path_keywords: tuple[str, ...] = ()
    priority: int = 10


def _load_gov_domains_from_sources(s: Settings) -> list[GovDomain]:
    """从 config/sources.yaml 加载白名单。

    简化实现:MVP 阶段不解析 sources.yaml(避免额外 IO 与耦合),
    直接在代码中内置与 sources.yaml 对应的白名单,
    后续可改成读 sources.yaml 并动态加载。
    """
    # 与 config/sources.yaml gov_sources.domains 保持一致
    return [
        GovDomain(name="国家统计局", domain="www.stats.gov.cn", priority=1),
        GovDomain(name="工信部",     domain="www.miit.gov.cn",   priority=1),
        GovDomain(name="农业农村部",  domain="www.moa.gov.cn",    priority=2),
        GovDomain(name="省统计局(通用)", pattern="*.stats.gov.cn", priority=2),
        GovDomain(
            name="省政府(通用)",
            pattern="*.gov.cn",
            path_keywords=("tjgb", "fzgh", "cyfz", "zmhd", "zhengce", "jihua"),
            priority=3,
        ),
    ]


class GovDataProvider(SearchProvider):
    """政府公开数据搜索 + 详情页抓取。

    实现策略:search(query) 内部会跑
        1) 组装 county/focus 相关政府查询(复用 sources.yaml 的模板思路)
        2) 用 web_provider 搜索
        3) 过滤白名单 + 抓详情页
    调用方传普通 query 也能工作,但效果最好的是传带县名+方向的结构化 query。
    """

    name = "gov"

    def __init__(
        self,
        *,
        web_provider: SearchProvider | None = None,
        settings: Settings | None = None,
        fetch_detail: bool | None = None,
        detail_max_chars: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        s = self._settings.search
        # 复用一个已配置好的 Web SearchProvider(支持 Key 注入)
        self._web: SearchProvider = web_provider or create_provider(settings=self._settings)
        self._domains = _load_gov_domains_from_sources(self._settings)
        self._fetch_detail = fetch_detail if fetch_detail is not None else s.fetch_detail
        self._detail_max_chars = detail_max_chars or s.detail_max_chars
        self._timeout = timeout or float(s.timeout)
        self._retry_cfg = s.retry
        self._max_results = s.max_results

    # ---- SearchProvider 接口 ----

    def search(self, query: str, max_results: int = 10) -> list[RawDoc]:
        """执行政府数据搜索(三步骤:搜→过滤→抓详情)。"""
        # 1) 使用 Web provider 搜索
        raw = self._web.search(query, max_results=max_results or self._max_results)

        # 2) 白名单过滤
        filtered = [d for d in raw if self._match_whitelist(d.url)]
        logger.info("政府搜索过滤 | input=%d, after_whitelist=%d", len(raw), len(filtered))
        if not filtered:
            return []

        # 3) 抓详情页(按 settings.search.fetch_detail)
        if not self._fetch_detail:
            # 不抓详情页,仅返回 snippet
            for d in filtered:
                d.source = self.name
            return filtered[: max_results or self._max_results]

        enriched: list[RawDoc] = []
        for doc in filtered:
            try:
                enriched.append(self._enrich_with_detail(doc))
            except SearchError as e:
                logger.warning("政府页面抓取失败 | url=%s | err=%s", doc.url, e)
                # 单个页面失败不阻断,退化为 snippet
                enriched.append(doc)

        return enriched[: max_results or self._max_results]

    # ---- 白名单匹配 ----

    def _match_whitelist(self, url: str) -> bool:
        if not url:
            return False
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = parsed.hostname or ""
        path = parsed.path or ""
        if not host:
            return False

        for gd in self._domains:
            # 精确域名
            if gd.domain and host == gd.domain:
                return self._match_path(path, gd.path_keywords)
            # Glob 模式
            if gd.pattern and (
                fnmatch.fnmatch(host, gd.pattern) or host.endswith(gd.pattern.lstrip("*."))
            ):
                return self._match_path(path, gd.path_keywords)
        return False

    @staticmethod
    def _match_path(path: str, keywords: tuple[str, ...]) -> bool:
        """path 关键词过滤;无关键词则放行。"""
        if not keywords:
            return True
        return any(kw in path.lower() for kw in keywords)

    # ---- 详情页抓取 ----

    def _enrich_with_detail(self, doc: RawDoc) -> RawDoc:
        """抓取详情页 HTML,用 BeautifulSoup 提取正文。"""
        # 延迟导入 BeautifulSoup(用户可能还没装 bs4)
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise SearchError(
                "抓取详情页需要 beautifulsoup4,当前未安装",
                context={"hint": "pip install beautifulsoup4", "error": str(e)},
            ) from e

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
        def _fetch(url: str) -> str:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (CountyResearchAI/0.1 bot)",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code >= 400:
                        raise SearchError(
                            f"HTTP {resp.status_code} 抓取政府页面失败",
                            context={"url": url},
                        )
                    return resp.text
            except SearchError:
                raise
            except httpx.HTTPError as e:
                raise SearchError(
                    f"网络错误抓取政府页面: {type(e).__name__}",
                    context={"url": url, "error": str(e)},
                ) from e

        try:
            html = _fetch(doc.url)
        except RetryError as e:
            raise SearchError(
                "抓取政府页面重试耗尽",
                context={"url": doc.url, "attempts": self._retry_cfg.max_attempts, "last_error": str(e)},
            ) from e

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        # 正文提取:MVP 取 <article> 或 <body>,清理多空格与空行
        main = soup.find("article") or soup.find("main") or soup.find("body") or soup
        text = main.get_text(separator="\n", strip=True)
        # 折叠连续空行
        import re as _re
        text = _re.sub(r"\n{3,}", "\n\n", text)

        # 长度截断
        if self._detail_max_chars > 0 and len(text) > self._detail_max_chars:
            text = text[: self._detail_max_chars - 3] + "..."

        return RawDoc(
            title=doc.title or (soup.title.string if soup.title and soup.title.string else ""),
            url=doc.url,
            snippet=doc.snippet,
            content=text,
            source=self.name,
            fetched_at=datetime.now(timezone.utc),
            metadata={**doc.metadata, "detail_fetched": True},
        )
