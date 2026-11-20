"""Bounded, cached public-web search/fetch adapters for retrieval recovery.

This is not a paid provider and not a general crawler. It queries DuckDuckGo's
public HTML endpoint for a small, bounded number of queries, fetches a few
result pages, and caches every response with a content hash. Callers must keep
query/page counts low and respect public-site availability.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "AxiomScopeResearch/0.1"
)
DDG_HTML = "https://html.duckduckgo.com/html/"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    status: int
    title: str
    text: str
    content_hash: str
    retrieved_at: str
    error: str = ""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decode_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        query = urllib.parse.urlparse(href).query
        values = urllib.parse.parse_qs(query).get("uddg", [])
        if values:
            return urllib.parse.unquote(values[0])
    return href


def parse_ddg_results(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for link in soup.select("a.result__a"):
        href = _decode_url(link.get("href", ""))
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        title = link.get_text(" ", strip=True)
        snippet = ""
        parent = link.find_parent("div", class_="result")
        if parent is not None:
            node = parent.select_one(".result__snippet")
            if node is not None:
                snippet = node.get_text(" ", strip=True)
        results.append(SearchResult(title=title, url=href, snippet=snippet))
    return results


def page_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return title, re.sub(r"\n{2,}", "\n", text)


def _cjk_score(text: str) -> int:
    cjk = sum(1 for char in text if "一" <= char <= "鿿")
    return cjk - 3 * text.count("�")


def decode_html(content: bytes, header_encoding: str | None = None) -> str:
    """Decode Chinese public pages without trusting a wrong charset header."""
    try:
        utf8_text = content.decode("utf-8")
        if "�" not in utf8_text:
            return utf8_text
    except UnicodeDecodeError:
        pass
    candidates: list[str] = []
    if header_encoding:
        candidates.append(header_encoding)
    match = re.search(
        rb"charset\s*=\s*[\"']?([a-zA-Z0-9_\-]+)", content[:4096], re.IGNORECASE
    )
    if match:
        candidates.append(match.group(1).decode("ascii", errors="ignore"))
    candidates.extend(["utf-8", "gb18030", "gbk", "big5"])
    best_text = ""
    best_score = -10**9
    for encoding in dict.fromkeys(candidates):
        try:
            decoded = content.decode(encoding, errors="replace")
        except LookupError:
            continue
        score = _cjk_score(decoded)
        if score > best_score:
            best_score = score
            best_text = decoded
    return best_text or content.decode("utf-8", errors="replace")


class FreeWebClient:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        max_retries: int = 2,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.search_cache = self.cache_dir / "search"
        self.page_cache = self.cache_dir / "pages"
        self.search_cache.mkdir(parents=True, exist_ok=True)
        self.page_cache.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0
        self.request_count = 0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()
        self.request_count += 1

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = _sha(query)
        cache = self.search_cache / f"{key}.json"
        if cache.is_file():
            rows = json.loads(cache.read_text(encoding="utf-8"))
            return [SearchResult(**row) for row in rows][:max_results]
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                self._wait()
                response = httpx.get(
                    DDG_HTML,
                    params={"q": query},
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                if response.status_code in {202, 429, 503}:
                    last_error = f"http_{response.status_code}"
                    time.sleep(2.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                results = parse_ddg_results(response.text)
                cache.write_text(
                    json.dumps(
                        [result.__dict__ for result in results],
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return results[:max_results]
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(1.5 * (attempt + 1))
        cache.write_text("[]\n", encoding="utf-8")
        _ = last_error
        return []

    def fetch(self, url: str, *, max_chars: int = 120_000) -> PageSnapshot:
        key = _sha(url)
        cache = self.page_cache / f"{key}.json"
        if cache.is_file():
            payload = json.loads(cache.read_text(encoding="utf-8"))
            return PageSnapshot(**payload)
        now = datetime.now(timezone.utc).isoformat()
        status = 0
        title = ""
        text = ""
        error = ""
        for attempt in range(self.max_retries + 1):
            try:
                self._wait()
                response = httpx.get(
                    url,
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                status = response.status_code
                if status in {202, 429, 503}:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                content_type = response.headers.get("content-type", "")
                if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                    error = "pdf_not_parsed"
                    break
                html = decode_html(response.content, response.encoding)
                title, text = page_text(html)
                text = text[:max_chars]
                if status >= 400:
                    error = f"http_{status}"
                break
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                time.sleep(1.5 * (attempt + 1))
        snapshot = PageSnapshot(
            url=url,
            status=status,
            title=title,
            text=text,
            content_hash=_sha(text),
            retrieved_at=now,
            error=error,
        )
        cache.write_text(
            json.dumps(snapshot.__dict__, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return snapshot
