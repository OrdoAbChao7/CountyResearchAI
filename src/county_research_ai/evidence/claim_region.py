"""Claim-level region attribution.

A document may mention the target county while also carrying data about another
province, prefecture, or the nation. Document-level retrieval therefore cannot
authorise every extracted number as county evidence. This module classifies the
region of one claim from its own text, administrative scope, and document
heading or URL. A statistic with an omitted subject may inherit an outside
region within the same sentence. Positive county attribution still requires
claim-local or document-heading evidence.

The classification rules themselves live in :mod:`search.region_relevance`; this
module only composes the existing full-name, boundary-safe short-name, national,
and place-token rules for a claim-sized input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import RawDoc
from ..search.disambiguation import disambiguate_region, matches_explicit_parents
from ..search.region_relevance import (
    RegionVerdict,
    assess_region_relevance,
    county_name_terms,
    place_names,
)

_NATIONAL_MARKERS = ("全国", "国家统计局", "国务院", "中华人民共和国")
_UNKNOWN = "UNKNOWN"
_PLACE_SEPARATORS = re.compile(r"[与和及、，,；;：:/\\（）()《》【】\s]+")
_COMPARISON_REFERENCE = re.compile(
    r"(?:与|同(?![时比])|和)[^，,。；;：:\n（）()与]{1,24}?(?:相比|相较|作比较|对比)"
)
_SCOPE_SHARE_REFERENCE = re.compile(r"占(?:据|到)?(?:全国|全省|全市)([^，,。；;：:\n（）()]*)")
_ABSOLUTE_QUANTITY = re.compile(r"\d\s*(?:亿元|万元|万亩|亩|平方公里|吨|万斤|万件|万人|人|家|个|户|万|亿)")
_GENERIC_UPPER_SCOPE = re.compile(r"全省|全市|地级市")
# Match complete scope tokens so named counties such as 天全县 stay eligible.
_GENERIC_COUNTY_SCOPE_TOKEN = re.compile(r"本县|(?:年末|建议|今年|[年占本该国全])*全县")
_SENTENCE_BREAK = re.compile(r"[。；;！!？?\n]")
# Parentheses only separate observations if they contain another quantity.
_STATISTICAL_CLAUSE_TOKEN = re.compile(
    rf"(?P<aside>[（(](?![^（）()]*(?:{_ABSOLUTE_QUANTITY.pattern}|\d\s*[%％‰]))[^（）()]*[）)])"
    r"|[，（）()]|(?<!\d),|,(?!\d)"
)
_RETROSPECTIVE_SCOPE = re.compile(
    r"^(?:以上|上述|前述)(?:统计)?(?:数据|数值|指标|产值)?(?:均|仅)?"
    r"(?:的?统计(?:范围|口径|对象))?(?:为|是|指|属于|覆盖)(全国|全省|全市)"
)
_DENOMINATOR_INTRO = re.compile(r"(?:占(?:据|到)?|为|是|相当于|约合)\s*")
_FRACTION_SUFFIX = re.compile(r"^\s*的\s*(?:约|近)?\s*\d+(?:\.\d+)?\s*[%％‰]")
_EXPLICIT_LOCAL = re.compile(r"^(?:(?:19|20)\d{2}年[度末]?\s*)?(?:本县|全县)")
_PARENTHETICAL = re.compile(r"[（(]([^（）()]*)[）)]")
_RETRACTION = re.compile(r"错误|有误|不实|应为|更正")


def _fraction_denominator(prefix: str) -> str:
    for intro in reversed(list(_DENOMINATOR_INTRO.finditer(prefix))):
        operand = prefix[intro.end():]
        if operand.startswith(("全国", "全省", "全市")) or operand.startswith(place_names(operand)):
            return operand
    return ""


@dataclass(frozen=True)
class StatisticalValueContext:
    prefix: str
    amount: str
    suffix: str
    preceding_clauses: tuple[str, ...]
    following_scope: str
    retracted: bool

    @property
    def statement(self) -> str:
        return (self.prefix + self.amount + self.suffix).strip()


def statistical_value_context(text: str, start: int, end: int) -> StatisticalValueContext:
    """Return the statement and nearby scope cues for one value span."""
    sentence_start = 0
    for boundary in _SENTENCE_BREAK.finditer(text, 0, start):
        sentence_start = boundary.end()
    sentence_break = _SENTENCE_BREAK.search(text, end)
    sentence_end = sentence_break.start() if sentence_break else len(text)
    preceding: list[str] = []
    following: list[str] = []
    prefix_start, following_start = sentence_start, end
    for token in _STATISTICAL_CLAUSE_TOKEN.finditer(text, sentence_start, sentence_end):
        if token.lastgroup == "aside":
            continue
        if token.end() <= start:
            preceding.append(text[prefix_start:token.start()])
            prefix_start = token.end()
        elif token.start() >= end:
            following.append(text[following_start:token.start()])
            following_start = token.end()
    following.append(text[following_start:sentence_end])
    prefix, amount, suffix = text[prefix_start:start], text[start:end], following[0]
    # A correction can have its own amount, even when the corrected value's
    # statement stops at the opening parenthesis.
    note = _PARENTHETICAL.match(text, end + len(suffix), sentence_end)
    retracted = bool(_RETRACTION.search(suffix) or (note and _RETRACTION.search(note[1])))

    if _ABSOLUTE_QUANTITY.search(amount):
        if _FRACTION_SUFFIX.match(suffix) and (denominator := _fraction_denominator(prefix)):
            prefix, suffix = denominator, ""
        elif _SCOPE_SHARE_REFERENCE.match(suffix.lstrip().removeprefix("约")):
            suffix = ""

    if sentence_break:
        # A separate sentence qualifies only when it explicitly points back.
        following.append(_SENTENCE_BREAK.split(text[sentence_break.end():], maxsplit=1)[0])
    scope = next((
        match[1] for clause in following if (match := _RETROSPECTIVE_SCOPE.match(clause.strip()))
    ), "")
    return StatisticalValueContext(prefix, amount, suffix, tuple(preceding), scope, retracted)


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


def _without_comparison_references(text: str) -> str:
    def strip_share_reference(match: re.Match[str]) -> str:
        # An absolute quantity inside a comparison still belongs to its denominator.
        remainder = match.group(1)
        return match.group(0) if _ABSOLUTE_QUANTITY.search(remainder) else f" {remainder}"

    return _SCOPE_SHARE_REFERENCE.sub(strip_share_reference, _COMPARISON_REFERENCE.sub(" ", text))


def _statistical_scope(text: str, county: str) -> str:
    is_national_gdp = "国内生产总值" in text and (not county or county not in text)
    if "全国" in text or is_national_gdp:
        return "全国范围"
    if "全市" in text or "地级市" in text:
        return "全市范围"
    if "全省" in text:
        return "全省范围"
    return "县域本级"


def _named_scope(region: ClaimRegion, scope: str) -> str:
    if scope == "县域本级" and region.excluded_from_target:
        if region.region_id.endswith(("省", "自治区")):
            return "全省范围"
        if region.verdict is RegionVerdict.CONTEXT and region.region_id.endswith("市"):
            return "全市范围"
    return scope


def classify_statistical_claim_region(
    county: str, *, title: str, url: str, context: StatisticalValueContext, inherit_local_subject: bool = False,
) -> tuple[ClaimRegion, str]:
    subject = _without_comparison_references(context.prefix + context.amount).strip()
    scope = _statistical_scope(subject, county)
    region = classify_claim_region(county, title=title, url=url, statement=subject, scope=scope)
    if region.reason == "conflicting_parent_region":
        return region, scope
    if context.following_scope or (scope != "县域本级" and region.is_target):
        # Explicit scope controls the amount even if the report names a county.
        scope = _statistical_scope(context.following_scope, county) if context.following_scope else scope
        return classify_claim_region(county, title=title, url=url, scope=scope), scope
    if region.source in {"claim", "scope"}:
        return region, _named_scope(region, scope)

    # An omitted subject can inherit an outside region only in the same
    # sentence. 本县 and 全县 reset the subject to the document's county.
    if not _EXPLICIT_LOCAL.match(subject):
        for prior in reversed(context.preceding_clauses):
            if not prior.strip() or _SCOPE_SHARE_REFERENCE.match(prior.strip().removeprefix("约")):
                continue
            prior_scope = _statistical_scope(_without_comparison_references(prior), county)
            attribution = classify_claim_region(county, statement=prior, scope=prior_scope)
            if attribution.excluded_from_target or attribution.reason == "conflicting_parent_region":
                return attribution, _named_scope(attribution, prior_scope)
            if attribution.is_target:
                if inherit_local_subject:
                    return attribution, prior_scope
                break
            if _EXPLICIT_LOCAL.match(prior.strip()):
                break

    # Keep mixed-scope headings conservative for numbers with no local subject.
    title_scope = _statistical_scope(title, county)
    if title_scope != scope:
        region = classify_claim_region(county, title=title, url=url, statement=subject, scope=title_scope)
    return region, title_scope


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

    A generic ``全县`` phrase is not an administrative place name. It is
    removed from the claim tokens rather than treated as competition for the
    target; the document fallback still decides whether the claim belongs to
    the county. This preserves the rule that one county mention in a long
    document must not relabel every number in it.
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

    claim_text = _without_comparison_references(statement or quote).strip()
    if not (matches_explicit_parents(disambiguation, claim_text) and matches_explicit_parents(disambiguation, title)):
        return ClaimRegion(
            _UNKNOWN, "unknown", RegionVerdict("unknown"),
            target_region=target, reason="conflicting_parent_region",
        )
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

    # Give the generic directive boundaries so its 省 suffix cannot attach
    # to preceding words and look like a named province.
    place_text = re.sub(r"(?<!\d)(?:19|20)\d{2}年[度末]?", " ", claim_text)
    place_text = _GENERIC_UPPER_SCOPE.sub(" ", place_text)
    place_text = place_text.replace("完成省市下达", "完成 省市 下达")
    claim_tokens = tuple(
        token
        for token in place_names(_PLACE_SEPARATORS.sub(" ", place_text))
        if not _GENERIC_COUNTY_SCOPE_TOKEN.fullmatch(token)
    )
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

    explicit_scope = _statistical_scope(claim_text, target)
    has_explicit_scope = explicit_scope != "县域本级"
    decision_scope = explicit_scope if has_explicit_scope else scope
    scope_region = _scope_region(
        decision_scope,
        province=disambiguation.province,
        prefecture=disambiguation.prefecture,
    )
    if scope_region is not None:
        region_id, verdict = scope_region
        return ClaimRegion(
            region_id,
            "claim" if has_explicit_scope else "scope",
            verdict,
            target_region=target,
            matched_terms=(region_id,),
            reason=f"scope:{decision_scope}",
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
