"""Conservative answer targets for explicit county-industry questions.

The question remains the retrieval target even when its meaning cannot be
checked with these deterministic rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..search.disambiguation import (
    DisambiguationResult,
    disambiguate_region,
    matches_explicit_parents,
)
from .research_contracts import AtomicClaim, QuestionSlot

_YEAR = r"(?:19|20)\d{2}"
_QUESTION_YEAR = re.compile(rf"(?<!\d)({_YEAR})\s*年")
_PERIOD_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")
_CONTRACT_WINDOW = re.compile(r"(?:(\d{4})-\d\d-\d\d)?~(?:(\d{4})-\d\d-\d\d)?")
_TOTAL = re.compile(r"([\w·]*总产值|地区生产总值)(?:是|为)?多少(?:亿元|万元|元)?")
_ENTERPRISES = re.compile(r"有哪些([\w·]+(?:龙头企业|链主企业))")
_ENTERPRISES_REVERSED = re.compile(r"([\w·]+(?:龙头企业|链主企业))有哪些")
_COMPANY = r"[一-鿿A-Za-z0-9·（）()]{2,40}(?:有限公司|有限责任公司|集团)"
_NON_FACT = re.compile(
    r"计划|力争|预计|预测|拟(?:将|于|认定|列|公示|入选|入围|推荐|评定|确定)|建议|培育|目标|"
    r"尚未|待认定|撤销|取消|并非|不是|未获|征求意见|候选"
)
_SENTENCES = re.compile(r"[。；;！？!?\n]")
_PARTIAL_YEAR = re.compile(r"[上下]半年|季度|前[一二三四五六七八九十\d]+个?月|\d{1,2}月")
_PARTIAL_SCOPE = re.compile(r"规模以上|规上|限额以上|限上|(?:仅|只)(?:纳入|统计)|样本企业")
_SCOPE_DECLARATION = re.compile(
    r"(?:本次|本报告|本文|以下|统计范围|统计口径|统计对象)|(?:仅|只)(?:纳入|统计|覆盖|包含)"
)


def contract_period_in_window(period: str, window: str) -> bool:
    """Compare reporting years to the inclusive year bounds of a contract window."""
    bounds = _CONTRACT_WINDOW.fullmatch(window)
    if bounds is None:
        return True
    low, high = bounds.groups()
    years = _PERIOD_YEAR.findall(period)
    return bool(years) and all((low or "0001") <= year <= (high or "9999") for year in years)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _body(text: str, region: DisambiguationResult, year: str) -> str:
    names = sorted({region.raw_name, region.full_name, region.clean_name} - {""}, key=len, reverse=True)
    prefixes = [rf"{re.escape(name)}(?:的)?" for name in names]
    prefixes.extend((rf"{year}年(?:度)?", "全县", "本县", "全年(?:的)?"))
    return re.sub(rf"^(?:{'|'.join(prefixes)})+", "", _compact(text))


@dataclass(frozen=True)
class QuestionTarget:
    kind: Literal["annual_total", "enterprise"]
    label: str
    year: str
    region: DisambiguationResult

    def matches_claim(self, slot: QuestionSlot, claim: AtomicClaim) -> bool:
        return not self.claim_issue(slot, claim)

    def claim_issue(self, slot: QuestionSlot, claim: AtomicClaim) -> str:
        if claim.region_id != self.region.clean_name:
            return "claim_region_mismatch"
        if not re.fullmatch(_YEAR, claim.period):
            return "reporting_period_unconfirmed"
        if (self.year and claim.period != self.year) or not contract_period_in_window(claim.period, slot.time_period):
            return "outside_requested_period"
        statement = _body(claim.statement, self.region, claim.period).rstrip("。")
        label = re.escape(self.label)
        if self.kind == "annual_total":
            if claim.unit not in {"元", "万元", "亿元", "万", "亿"}:
                return "incompatible_unit"
            if not re.fullmatch(r"\d+(?:\.\d+)?", claim.value):
                return "missing_numeric_value"
            amount = re.escape(claim.value + claim.unit)
            pattern = rf"(?:实现|完成)?{label}(?:实现|完成|达到|达|约为|约|为)?{amount}"
        else:
            if claim.value:
                return "different_metric_or_qualification"
            pattern = (
                rf"{_COMPANY}(?:是|为|获认定为|被认定为|被列为){label}"
                rf"|{label}(?:包括|有|名单[:：]){_COMPANY}"
            )
        return "" if re.fullmatch(pattern, statement) else "different_metric_or_qualification"

    def has_factual_quote(
        self, claim: AtomicClaim, quote: str, *, title: str = "", content: str = "",
    ) -> bool:
        return not self.quote_issue(claim, quote, title=title, content=content)

    def quote_issue(
        self, claim: AtomicClaim, quote: str, *, title: str = "", content: str = "",
    ) -> str:
        """Check the local statement and any declared scope in the source."""
        if _NON_FACT.search(title):
            return "provisional_or_nonfactual"
        if not matches_explicit_parents(self.region, title):
            return "source_region_mismatch"
        annual = self.kind == "annual_total"
        if annual and (_PARTIAL_SCOPE.search(title) or any(
            _SCOPE_DECLARATION.search(sentence) and _PARTIAL_SCOPE.search(sentence)
            for sentence in _SENTENCES.split(content or quote)
        )):
            return "partial_statistics_scope"
        statement = _compact(claim.statement).rstrip("。")
        issue = "direct_statement_missing"
        for sentence in _SENTENCES.split(quote):
            text = _compact(sentence)
            separator = r"[，,（）()]" if annual else r"[，,]"
            if statement not in re.split(separator, text):
                continue
            if _NON_FACT.search(text):
                issue = "provisional_or_nonfactual"
            elif not matches_explicit_parents(self.region, text):
                issue = "source_region_mismatch"
            elif annual and _PARTIAL_SCOPE.search(text):
                issue = "partial_statistics_scope"
            elif annual and _PARTIAL_YEAR.search(text):
                issue = "partial_reporting_period"
            else:
                years = set(_QUESTION_YEAR.findall(text))
                if years == {claim.period}:
                    return ""
                if not years and annual and "全年" in text:
                    from ..document_period import bulletin_reporting_year

                    if bulletin_reporting_year(title) == claim.period:
                        return ""
                issue = "reporting_period_unconfirmed"
        return issue


def question_target(slot: QuestionSlot) -> QuestionTarget | None:
    """Recognize one metric or one named-enterprise qualification."""
    years = set(_QUESTION_YEAR.findall(slot.research_question))
    if len(years) > 1:
        return None
    region = disambiguate_region(_compact(slot.region))
    body = _body(slot.research_question, region, _YEAR).rstrip("?？")
    year = next(iter(years), "")
    if match := _TOTAL.fullmatch(body):
        return QuestionTarget("annual_total", match[1], year, region)
    if match := _ENTERPRISES.fullmatch(body) or _ENTERPRISES_REVERSED.fullmatch(body):
        return QuestionTarget("enterprise", match[1], year, region)
    return None
