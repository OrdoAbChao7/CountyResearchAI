"""Deterministic region relevance gate for county-scoped retrieval.

The live smoke on 2026-11-20 returned national statistics, another province's
statistical bulletin and another city's five-year plan for an `安吉县 竹产业`
contract. Those documents are not evidence about the county, and the evidence
store would have tagged their numbers with the county's scope. This module
classifies a result by the region it actually names, before anything is ranked
or ingested:

- ``REGION``: names the target county (or its distinctive short name);
- ``CONTEXT``: names only the target province/prefecture, never the county;
- ``OTHER_REGION``: names a different province/city/county;
- ``NATIONAL``: a national statistical/government publication, or a title that
  announces national coverage, without naming the county;
- ``UNKNOWN``: no identifiable region.

Only ``REGION`` and ``UNKNOWN`` are evidence-bearing. ``UNKNOWN`` is kept
because county government pages and company releases often omit the place name
from the title; the other verdicts positively identify a scope that is not the
county, so they are dropped before ranking and ingestion.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from ..models import RawDoc
from .disambiguation import disambiguate_region

_ADMIN_SUFFIXES = ("自治县", "自治旗", "自治区", "特区", "林区", "旗", "县", "市", "区", "州", "盟")

# A run of CJK characters followed by an administrative suffix. Examples:
# 安吉县, 浙江省, 洛阳市, 福建省. The group is greedy, so a stacked name like
# 浙江省安吉县 is returned as one token.
_PLACE_PATTERN = re.compile(
    r"[一-鿿]{2,8}(?:自治县|自治旗|自治区|省|市|县|区|州|盟|旗)"
)

# Compounds that end in an administrative suffix but are not place names.
_NON_PLACE_MARKERS = (
    "政府",
    "园区",
    "开发区",
    "高新区",
    "示范区",
    "试验区",
    "工业区",
    "新区",
    "市区",
    "城区",
    "辖区",
    "郊区",
    "地区",
    "景区",
    "小区",
    "社区",
    "学区",
    "库区",
    "牧区",
    "矿区",
    "保税区",
    "自贸区",
    "商务区",
    "物流区",
    "旅游区",
    "集中区",
    "集聚区",
)

# National outlets and portals. A path on a local `*.gov.cn` site must not be
# treated as national, so only these exact domains (or their subdomains) match.
_NATIONAL_HOSTS = (
    "stats.gov.cn",
    "miit.gov.cn",
    "moa.gov.cn",
    "ndrc.gov.cn",
    "forestry.gov.cn",
)

# Title-level markers that announce national coverage. Checked only after the
# county itself was not mentioned, so "安吉县全国百强县" still counts as REGION.
_NATIONAL_TITLE_MARKERS = ("国家统计局", "中华人民共和国", "国务院", "全国")
_NATIONAL_TEXT_MARKERS = ("国家统计局", "中华人民共和国", "国务院")


class RegionVerdict(StrEnum):
    REGION = "region"
    CONTEXT = "context"
    OTHER_REGION = "other_region"
    NATIONAL = "national"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegionAssessment:
    verdict: RegionVerdict
    matched_terms: tuple[str, ...] = ()
    other_regions: tuple[str, ...] = ()
    reason: str = ""

    @property
    def evidence_bearing(self) -> bool:
        """Whether this document may be ingested as evidence about the county."""
        return self.verdict in {RegionVerdict.REGION, RegionVerdict.UNKNOWN}


@dataclass(frozen=True)
class RegionFilterResult:
    kept: tuple[RawDoc, ...]
    dropped: tuple[tuple[RawDoc, RegionAssessment], ...]


def _short_name(clean_name: str) -> str:
    for suffix in _ADMIN_SUFFIXES:
        if clean_name.endswith(suffix) and len(clean_name) > len(suffix):
            short = clean_name[: -len(suffix)]
            return short if len(short) >= 2 else ""
    return clean_name if len(clean_name) >= 2 else ""


def _county_terms(county: str) -> tuple[str, ...]:
    disambiguation = disambiguate_region(county)
    clean_name = (disambiguation.clean_name or county).strip()
    if not clean_name:
        return ()
    terms = [clean_name]
    short = _short_name(clean_name)
    if short and short != clean_name:
        terms.append(short)
    return tuple(dict.fromkeys(terms))


def _host_is_national(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in {"gov.cn", "www.gov.cn"}:
        return True
    return any(host == domain or host.endswith("." + domain) for domain in _NATIONAL_HOSTS)


def _place_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _PLACE_PATTERN.finditer(text or ""):
        token = match.group(0)
        if token in tokens:
            continue
        if any(marker in token for marker in _NON_PLACE_MARKERS):
            continue
        tokens.append(token)
    return tuple(tokens)


def assess_region_relevance(document: RawDoc, county: str) -> RegionAssessment:
    """Classify one search result against the requested county."""
    county = (county or "").strip()
    if not county:
        return RegionAssessment(RegionVerdict.UNKNOWN, reason="no_region_requested")

    terms = _county_terms(county)
    title = document.title or ""
    snippet = document.snippet or ""
    haystack = "\n".join(
        (title, snippet, document.url or "", (document.content or "")[:3000])
    )
    matched = tuple(term for term in terms if term in haystack)
    if matched:
        return RegionAssessment(
            RegionVerdict.REGION,
            matched_terms=matched,
            reason="county_mentioned",
        )

    if _host_is_national(document.url) or any(
        marker in title for marker in _NATIONAL_TITLE_MARKERS
    ) or any(marker in f"{title}\n{snippet}" for marker in _NATIONAL_TEXT_MARKERS):
        return RegionAssessment(RegionVerdict.NATIONAL, reason="national_source")

    disambiguation = disambiguate_region(county)
    context_terms = tuple(
        term
        for term in (disambiguation.province, disambiguation.prefecture)
        if term
    )
    tokens = _place_tokens(f"{title}\n{snippet}")
    other_regions = tuple(
        token
        for token in tokens
        if not any(term in token for term in context_terms)
    )
    if other_regions:
        return RegionAssessment(
            RegionVerdict.OTHER_REGION,
            other_regions=other_regions,
            reason="other_region_named",
        )
    if tokens:
        return RegionAssessment(
            RegionVerdict.CONTEXT,
            matched_terms=tokens,
            reason="upper_level_only",
        )
    return RegionAssessment(RegionVerdict.UNKNOWN, reason="no_region_signal")


def filter_documents_for_region(
    documents: Iterable[RawDoc],
    county: str,
) -> RegionFilterResult:
    """Split results into evidence-bearing and region-excluded documents."""
    kept: list[RawDoc] = []
    dropped: list[tuple[RawDoc, RegionAssessment]] = []
    for document in documents:
        assessment = assess_region_relevance(document, county)
        if assessment.evidence_bearing:
            kept.append(document)
        else:
            dropped.append((document, assessment))
    return RegionFilterResult(kept=tuple(kept), dropped=tuple(dropped))
