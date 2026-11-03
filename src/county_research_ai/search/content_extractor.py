"""网页正文抽取、URL 规范化、去重与相关性重排器。

提供：
1. URL 规范化（去除 tracking 参数、统一大小写与协议）；
2. 跨站重复内容识别（基于标准化文本与指纹 hash）；
3. 统计年份与发布时间抽取；
4. 混合相关性重排序（结合关键词匹配、权威域名权重、时效性加权与标题命中）。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..models import RawDoc

# 常见追踪参数黑名单
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "ref", "source", "ssid", "wd", "oq", "usg", "ved",
    "_t", "timestamp", "signature", "token", "t", "rand", "random",
}

# 权威政府与研究机构域名模式
_GOV_DOMAINS = ("gov.cn", "stats.gov.cn", "moa.gov.cn", "miit.gov.cn", "ndrc.gov.cn")
_RESEARCH_DOMAINS = ("cnki.net", "cas.cn", "cass.org.cn", "caas.cn", "edu.cn")
_MAINSTREAM_NEWS = ("xinhuanet.com", "people.com.cn", "cctv.com", "chinadaily.com.cn", "ce.cn")


def normalize_url(url: str) -> str:
    """规范化 URL，去除无意义参数并归一化。"""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        if not parsed.netloc:
            return url.strip()

        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # 过滤追踪 query 参数
        filtered_queries = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=False):
            if k.lower() not in _TRACKING_PARAMS:
                filtered_queries.append((k, v))

        query_str = urlencode(filtered_queries)
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

        clean = urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path,
            "",  # params
            query_str,
            "",  # fragment
        ))
        return clean
    except Exception:
        return url.strip()


def extract_publish_date(text: str, url: str = "") -> datetime | None:
    """从文本或 URL 中提取发布日期或主要年份。"""
    # 1. 尝试从 URL 中匹配日期，如 /2023-05-18/ 或 /20230518/
    url_date_match = re.search(r"/(20[12]\d)[-_/]?(0[1-9]|1[0-2])[-_/]?(0[1-9]|[12]\d|3[01])", url)
    if url_date_match:
        try:
            year, month, day = (int(url_date_match.group(i)) for i in (1, 2, 3))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass

    # 2. 尝试从正文中提取 "2023年5月18日" 或 "2023-05-18"
    text_date_match = re.search(
        r"(20[12]\d)[年\-/](0?[1-9]|1[0-2])[月\-/]([12]\d|3[01]|0?[1-9])日?",
        text[:500],  # 优先看开头
    )
    if text_date_match:
        try:
            year = int(text_date_match.group(1))
            month = int(text_date_match.group(2))
            day = int(text_date_match.group(3))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass

    # 3. 仅提取年份
    year_match = re.search(r"(20[12]\d)年", text[:500])
    if year_match:
        try:
            year = int(year_match.group(1))
            return datetime(year, 1, 1, tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def calculate_content_fingerprint(text: str) -> str:
    """计算文本的标准化指纹（过滤标点空白后取 MD5），用于识别跨站转载。"""
    cleaned = re.sub(r"[\s\W\d_]+", "", text[:1000])
    if len(cleaned) < 30:
        return ""
    return hashlib.md5(cleaned.encode("utf-8"), usedforsecurity=False).hexdigest()


def rerank_documents(
    docs: list[RawDoc],
    keywords: list[str],
    county: str = "",
    top_k: int = 0,
) -> list[RawDoc]:
    """多维混合相关度重排序。

    综合考虑：
    1. 标题与县名、核心关键词精确匹配（Title Boost）
    2. 域名权威性权重（.gov.cn > 权威科研 > 主流央媒 > 商业自媒体）
    3. 统计与公报核心专业词命中（公报/产值/规划）
    4. 文本长度与信息密度（正文充足者优先）
    5. 时效性加权（近年数据加分）
    """
    clean_kws = [kw for kw in keywords if kw]
    county_re = re.compile(re.escape(county)) if county else None
    stat_re = re.compile(r"统计公报|国民经济|十四五|总产值|规上工业|发展规划|种植面积|增加值")

    def _calculate_score(doc: RawDoc) -> float:
        score = 0.0
        title = doc.title or ""
        snippet = doc.snippet or ""
        content = doc.content or ""
        full_text = f"{title} {snippet} {content}"
        url_lower = (doc.url or "").lower()

        # 1. 域名权威性
        if any(d in url_lower for d in _GOV_DOMAINS) or doc.domain_type == "government":
            score += 5.0
            doc.credibility_score = max(doc.credibility_score, 0.95)
        elif any(d in url_lower for d in _RESEARCH_DOMAINS) or doc.domain_type == "research":
            score += 4.0
            doc.credibility_score = max(doc.credibility_score, 0.88)
        elif any(d in url_lower for d in _MAINSTREAM_NEWS) or doc.domain_type == "news":
            score += 3.0
            doc.credibility_score = max(doc.credibility_score, 0.78)
        else:
            score += 1.0

        # 2. 标题命中县名与关键词
        if county_re and county_re.search(title):
            score += 4.0
        for kw in clean_kws:
            if kw in title:
                score += 3.0
            elif kw in snippet:
                score += 1.0

        # 3. 统计公报及专业词命中
        stat_matches = len(stat_re.findall(full_text))
        score += min(stat_matches * 0.8, 4.0)

        # 4. 正文丰富度
        if len(content) > 300:
            score += 2.0
        elif len(content) > 100:
            score += 1.0

        # 5. 时效性（2022-2026年加分，2018年之前降分）
        if re.search(r"202[3-6]年?", full_text):
            score += 2.0
        elif re.search(r"202[1-2]年?", full_text):
            score += 1.0
        elif re.search(r"201[0-7]年", full_text) and not re.search(r"202[0-6]年", full_text):
            score -= 1.0

        return score

    # 排序
    scored_docs = sorted(docs, key=_calculate_score, reverse=True)
    if top_k and top_k < len(scored_docs):
        return scored_docs[:top_k]
    return scored_docs
