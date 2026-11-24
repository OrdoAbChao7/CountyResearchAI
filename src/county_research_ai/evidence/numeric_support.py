"""Bind a numerical observation to its local subject and direction.

No semantic entailment is claimed. Ambiguous fragments fail closed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..domain.research_contracts import AtomicClaim
from .claim_region import classify_statistical_claim_region, statistical_value_context
from .measure import (
    canonical_reporting_period,
    data_years,
    local_reporting_period,
    strip_subannual_period,
)

NUMBER = re.compile(
    r'(?<![\d.])([+\-−]?\d+(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(亿元|万元|万亩|千亩|平方公里|万吨|千吨|万斤|万件|万人|亿|万|%|‰|亩|吨|人|家|个|户)?'
)
DIRECTION = re.compile(r'下降|减少|降低|下滑|下跌|负增长|增长|增加|提高|上升|上涨|增幅|降幅|持平|不变')
NEGATIVE = {'下降', '减少', '降低', '下滑', '下跌', '负增长', '降幅'}
ZERO = {'持平', '不变'}
FACTORS = {'亿元': Decimal(10000), '亿': Decimal(10000),
           '万元': Decimal(1), '万': Decimal(1)}
_NON_EXACT_AMOUNT = re.compile(
    r"突破|超过|超(?=\s*\d)|不足|低于|高于|不超过|不少于|最多|最少|至少|至多|"
    r"约(?:为|合|(?=\s*\d))|接近|近(?=\s*\d)|逾|左右|(?<!规模)(?<!限额)以上|以下|预计|估计|力争|计划"
)


def has_exact_amount(statement: str) -> bool:
    return _NON_EXACT_AMOUNT.search(statement) is None


def _value(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(',', '').replace('−', '-'))
    except InvalidOperation:
        return None


def _direction(prefix: str, token: str) -> int | None:
    if token.startswith(('-', '−')):
        return -1
    words = DIRECTION.findall(prefix)
    if words:
        return -1 if words[-1] in NEGATIVE else (0 if words[-1] in ZERO else 1)
    return 1 if token.startswith('+') else None


def _subject(prefix: str) -> str:
    prefix = re.sub(r'(?:19|20)\d{2}年', '', strip_subannual_period(prefix))
    prefix = DIRECTION.sub('', prefix)
    prefix = re.sub(r'亿元|万元|亿|万|万人|人|亩', '', prefix)
    prefix = re.sub(r'[\d.%\s+\-−\[\]（）()]+|同比|较上年|比上年|其中|达到|实现|约|为', '', prefix)
    prefix = re.sub(r'^(?:全县|全市|全区|全年|初步核算|据统计|实际|本县)+', '', prefix)
    return prefix


def _amount_equal(numeric: Decimal, unit: str, target: Decimal, target_unit: str) -> bool:
    if unit in FACTORS and target_unit in FACTORS:
        return abs(numeric) * FACTORS[unit] == abs(target) * FACTORS[target_unit]
    return abs(numeric) == abs(target) and unit == target_unit


def numeric_context_matches(claim: AtomicClaim, quote: str, *, title: str = "", url: str = "") -> bool:
    target = _value(claim.value)
    if target is None:
        return False
    claim_match = next((m for m in NUMBER.finditer(claim.statement)
                        if (number := _value(m[1])) is not None
                        and _amount_equal(number, m[2] or "", target, claim.unit)), None)
    claim_prefix = claim.statement[:claim_match.start()] if claim_match else claim.statement
    direction = _direction(claim_prefix, claim_match[1] if claim_match else claim.value)
    # A concrete subject is stronger than the legacy coarse metric_id.
    subject = _subject(claim_prefix.replace(claim.region_id, '')) if claim.region_id else _subject(claim_prefix)
    metric = subject or _subject(claim.measure_id) or claim.metric_id
    claim_period = canonical_reporting_period(claim.period)
    claim_years = set(data_years(claim_period))
    for match in NUMBER.finditer(quote):
        numeric = _value(match[1])
        if numeric is None or not _amount_equal(numeric, match[2] or "", target, claim.unit):
            continue
        value_context = statistical_value_context(quote, match.start(), match.end())
        if value_context.retracted:
            continue
        prefix = value_context.prefix
        period = local_reporting_period(value_context.statement, preceding=value_context.preceding_clauses)
        if period and (len(claim_years) != 1 or period != claim_period):
            continue
        if not period and strip_subannual_period(claim_period) != claim_period:
            continue
        local_subject = _subject(prefix)
        if claim.region_id:
            region, _ = classify_statistical_claim_region(
                claim.region_id, title=title, url=url, context=value_context, inherit_local_subject=not local_subject,
            )
            if not region.is_target:
                continue
        # Only an explicitly subjectless continuation inherits its predecessor.
        preceding = next((clause for clause in reversed(value_context.preceding_clauses) if clause.strip()), "")
        context = prefix if local_subject else preceding + prefix
        context_subject = _subject(context.replace(claim.region_id, '')) if claim.region_id else _subject(context)
        if metric and metric != context_subject:
            continue
        if re.search(r'不增长|未增长|没有增长|并未|并非|不是', prefix):
            continue
        found_direction = _direction(prefix, match[1])
        if direction is not None and found_direction != direction:
            continue
        if numeric < 0 and direction != -1 and target >= 0:
            continue
        if target < 0 and numeric >= 0 and found_direction != -1:
            continue
        return True
    return False
