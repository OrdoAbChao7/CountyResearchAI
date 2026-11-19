"""Bind a numerical observation to its local subject and direction.

No semantic entailment is claimed. Ambiguous fragments fail closed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..domain.research_contracts import AtomicClaim
from .measure import data_years

NUMBER = re.compile(r'(?<![\d.])([+\-−]?\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|亿|万|%|‰|亩|万人|人)?')
CLAUSE = re.compile(r'([，。；;！？!?\n]|,(?!\d))')
DIRECTION = re.compile(r'下降|减少|降低|下滑|下跌|负增长|增长|增加|提高|上升|上涨|增幅|降幅|持平|不变')
NEGATIVE = {'下降', '减少', '降低', '下滑', '下跌', '负增长', '降幅'}
ZERO = {'持平', '不变'}
FACTORS = {'亿元': Decimal(10000), '亿': Decimal(10000),
           '万元': Decimal(1), '万': Decimal(1)}


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
    prefix = re.sub(r'(?:19|20)\d{2}年', '', prefix)
    prefix = DIRECTION.sub('', prefix)
    prefix = re.sub(r'亿元|万元|亿|万|万人|人|亩', '', prefix)
    prefix = re.sub(r'[\d.%\s+\-−\[\]（）()]+|同比|较上年|比上年|其中|达到|实现|约|为', '', prefix)
    prefix = re.sub(r'^(?:全县|全市|全区|全年|初步核算|据统计|实际|本县)+', '', prefix)
    return prefix


def _amount_equal(numeric: Decimal, unit: str, target: Decimal, target_unit: str) -> bool:
    if unit in FACTORS and target_unit in FACTORS:
        return abs(numeric) * FACTORS[unit] == abs(target) * FACTORS[target_unit]
    return abs(numeric) == abs(target) and unit == target_unit


def numeric_context_matches(claim: AtomicClaim, quote: str) -> bool:
    target = _value(claim.value)
    if target is None:
        return False
    claim_match = next((m for m in NUMBER.finditer(claim.statement)
                        if _value(m[1]) in (target, abs(target))), None)
    claim_prefix = claim.statement[:claim_match.start()] if claim_match else claim.statement
    direction = _direction(claim_prefix, claim_match[1] if claim_match else claim.value)
    # A concrete subject is stronger than the legacy coarse metric_id.
    subject = _subject(claim_prefix.replace(claim.region_id, '')) if claim.region_id else _subject(claim_prefix)
    metric = subject or _subject(claim.measure_id) or claim.metric_id
    previous = ''
    active_year = ''
    for clause in CLAUSE.split(quote):
        if clause in ('。', '；', ';', '！', '？', '!', '?', '\n'):
            previous = ''
            continue
        if clause in ('，', ','):
            continue
        for match in NUMBER.finditer(clause):
            numeric = _value(match[1])
            if numeric is None:
                continue
            unit = match[2] or ''
            if not _amount_equal(numeric, unit, target, claim.unit):
                continue
            prefix = clause[:match.start()]
            years = data_years(clause)
            if len(set(years)) > 1:
                continue
            if years:
                active_year = years[-1]
            claim_years = re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', claim.period)
            if active_year and active_year not in claim_years:
                continue
            local_subject = _subject(prefix)
            # Only an explicitly subjectless comma continuation inherits its predecessor.
            context = prefix if local_subject else previous + prefix
            context_subject = _subject(context.replace(claim.region_id, '')) if claim.region_id else _subject(context)
            if metric and metric != context_subject:
                continue
            if re.search(r'不增长|未增长|没有增长|并未|并非|不是', prefix):
                continue
            if re.search(r'错误|有误|不实|应为|更正', clause[match.end():]):
                continue
            found_direction = _direction(prefix, match[1])
            if direction is not None and found_direction != direction:
                continue
            if numeric < 0 and direction != -1 and target >= 0:
                continue
            if target < 0 and numeric >= 0 and found_direction != -1:
                continue
            return True
        previous = clause
        years = data_years(clause)
        if years:
            active_year = years[-1]
    return False
