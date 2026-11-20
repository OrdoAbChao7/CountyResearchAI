"""Claim-level region attribution.

A document may mention the target county while also carrying data about another
province, prefecture, or the nation. Document-level retrieval therefore cannot
authorise every extracted number as county evidence. This module classifies the
region of one claim from its own text first, then from the document's title and
URL, and finally from an explicit administrative scope. It deliberately does
not use the document body as a fallback: a county name anywhere in a long
article is not evidence that every number in that article belongs to the
county.

The classification rules themselves live in :mod:`search.region_relevance`; this
module only composes the existing full-name, boundary-safe short-name, national,
and place-token rules for a claim-sized input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import RawDoc
from ..search.disambiguation import disambiguate_region
from ..search.region_relevance import (
    RegionVerdict,
    assess_region_relevance,
    county_name_terms,
    place_names,
)

_NATIONAL_MARKERS = ("全国", "国家统计局", "国务院", "中华人民共和国")
_UNKNOWN = "UNKNOWN"
_PLACE_SEPARATORS = re.compile(r"[与和及、，,；;：:/\\（）()《》【】\s]+")


@dataclass(frozen=True)
class ClaimRegion:
    """Where a single claim's fact is located.

    ``source`` records why the attribution was made:
    ``claim`` (the claim text names the region), ``document`` (the title/URL
    names exactly one region), ``scope`` (an explicit national/provincial/
    prefecture scope), or ``unknown``.
    """

    region_id: str
    source: str
    verdict: RegionVerdict
    target_region: str = ""
    matched_terms: tuple[str, ...] = ()
    other_regions: tuple[str, ...] = ()
    reason: str = ""

    @property
    def is_target(self) -> bool:
        return bool(self.target_region) and self.region_id == self.target_region

    @property
    def is_unknown(self) -> bool:
        return (
            self.verdict is RegionVerdict.UNKNOWN
            or not self.region_id
            or self.region_id.upper() == _UNKNOWN
        )

    @property
    def excluded_from_target(self) -> bool:
        """True only when the claim positively belongs somewhere else."""
        return not self.is_unknown and not self.is_target


def _other_place_tokens(
    tokens: tuple[str, ...],
    *,
    full_name: str,
    short_name: str,
    context_terms: tuple[str, ...],
) -> tuple[str, ...]:
    other: list[str] = []
    for token in tokens:
        if full_name and full_name in token:
            continue
        if short_name and token == short_name:
            continue
        if any(term and term in token for term in context_terms):
            continue
        if token not in other:
            other.append(token)
    return tuple(other)


def _context_token(
    tokens: tuple[str, ...],
    *,
    context_terms: tuple[str, ...],
) -> str:
    for token in tokens:
        if any(term and term in token for term in context_terms):
            return token
    return ""


def _scope_region(
    scope: str,
    *,
    province: str,
    prefecture: str,
) -> tuple[str, RegionVerdict] | None:
    if not scope:
        return None
    if "全国" in scope:
        return "全国", RegionVerdict.NATIONAL
    if "全省" in scope:
        return province or "全省", RegionVerdict.CONTEXT
    if "全市" in scope or "地级市" in scope:
        return prefecture or "全市", RegionVerdict.CONTEXT
    return None


def classify_claim_region(
    county: str,
    *,
    title: str = "",
    url: str = "",
    statement: str = "",
    quote: str = "",
    scope: str = "",
) -> ClaimRegion:
    """Classify one claim's region without promoting it to the requested county.

    The order is intentional:

    1. an explicit full county name in the claim text;
    2. an explicit national marker or another named province/city/county in the
       claim text (county wins when both appear);
    3. an explicit non-county administrative scope;
    4. a document fallback only when the title/URL names exactly one region;
    5. otherwise ``UNKNOWN``.
    """
    clean_county = (county or "").strip()
    if not clean_county:
        return ClaimRegion(_UNKNOWN, "unknown", RegionVerdict.UNKNOWN)

    disambiguation = disambiguate_region(clean_county)
    target = (disambiguation.clean_name or clean_county).strip()
    full_name, short_name = county_name_terms(target)
    context_terms = tuple(
        term
        for term in (disambiguation.province, disambiguation.prefecture)
        if term
    )

    claim_text = "\n".join(part for part in (statement, quote) if part).strip()
    if full_name and full_name in claim_text:
        return ClaimRegion(
            target,
            "claim",
            RegionVerdict.REGION,
            target_region=target,
            matched_terms=(full_name,),
            reason="claim_names_county",
        )
    if any(marker in claim_text for marker in _NATIONAL_MARKERS):
        return ClaimRegion(
            "全国",
            "claim",
            RegionVerdict.NATIONAL,
            target_region=target,
            matched_terms=tuple(
                marker for marker in _NATIONAL_MARKERS if marker in claim_text
            ),
            reason="claim_names_national_scope",
        )

    claim_tokens = place_names(_PLACE_SEPARATORS.sub(" ", claim_text))
    other_tokens = _other_place_tokens(
        claim_tokens,
        full_name=full_name,
        short_name=short_name,
        context_terms=context_terms,
    )
    if other_tokens:
        return ClaimRegion(
            other_tokens[0],
            "claim",
            RegionVerdict.OTHER_REGION,
            target_region=target,
            other_regions=other_tokens,
            reason="claim_names_other_region",
        )
    context_token = _context_token(claim_tokens, context_terms=context_terms)
    if context_token:
        return ClaimRegion(
            context_token,
            "claim",
            RegionVerdict.CONTEXT,
            target_region=target,
            matched_terms=(context_token,),
            reason="claim_names_upper_level_only",
        )

    scope_region = _scope_region(
        scope,
        province=disambiguation.province,
        prefecture=disambiguation.prefecture,
    )
    if scope_region is not None:
        region_id, verdict = scope_region
        return ClaimRegion(
            region_id,
            "scope",
            verdict,
            target_region=target,
            matched_terms=(region_id,),
            reason=f"scope:{scope}",
        )

    # Document fallback uses title/URL only. Body content is intentionally not
    # consulted: one county mention in a long mixed article must not relabel
    # every number in that article.
    assessment = assess_region_relevance(
        RawDoc(title=title, url=url, content=""), target
    )
    if assessment.verdict is RegionVerdict.REGION:
        document_tokens = place_names(
            _PLACE_SEPARATORS.sub(" ", "\n".join((title, url)))
        )
        mixed = _other_place_tokens(
            document_tokens,
            full_name=full_name,
            short_name=short_name,
            context_terms=context_terms,
        )
        if mixed:
            return ClaimRegion(
                _UNKNOWN,
                "unknown",
                RegionVerdict.UNKNOWN,
                target_region=target,
                other_regions=mixed,
                reason="document_names_multiple_regions",
            )
        return ClaimRegion(
            target,
            "document",
            RegionVerdict.REGION,
            target_region=target,
            matched_terms=assessment.matched_terms,
            reason="document_names_county",
        )
    if assessment.verdict is RegionVerdict.NATIONAL:
        return ClaimRegion(
            "全国",
            "document",
            RegionVerdict.NATIONAL,
            target_region=target,
            reason="document_is_national",
        )
    if assessment.verdict is RegionVerdict.OTHER_REGION:
        regions = assessment.other_regions or ("OTHER_REGION",)
        return ClaimRegion(
            regions[0],
            "document",
            RegionVerdict.OTHER_REGION,
            target_region=target,
            other_regions=regions,
            reason="document_names_other_region",
        )
    if assessment.verdict is RegionVerdict.CONTEXT:
        return ClaimRegion(
            (assessment.matched_terms or (disambiguation.prefecture or "CONTEXT",))[0],
            "document",
            RegionVerdict.CONTEXT,
            target_region=target,
            matched_terms=assessment.matched_terms,
            reason="document_names_upper_level_only",
        )
    return ClaimRegion(
        _UNKNOWN,
        "unknown",
        RegionVerdict.UNKNOWN,
        target_region=target,
        reason=assessment.reason or "no_region_signal",
    )
