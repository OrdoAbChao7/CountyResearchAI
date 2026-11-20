"""Measure identity for claim conflict grouping.

Legacy claims frequently carry a coarse `metric_id` such as "产值与收入" and a
short fragment such as "增长4.3%". Grouping by the coarse metric makes different
measures look contradictory. This module derives a finer measure key from the
claim statement plus the surrounding source text, so 第一产业/第二产业/装备制造业
growth rates are not treated as the same fact.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_MARKDOWN = re.compile(r"[*`#\[\]()（）<>|]+")
_DIGITS = re.compile(r"[\d.,%‰]+")
_UNITS = re.compile(r"(亿元|万元|亿|万|%|‰|亩|万人|人|万吨|年|月|日)")
_PUNCT = re.compile(r"[，,。.;；:：、!?！？\"'“”‘’]+")
_LEADING = re.compile(
    r"^(其中|全年|全县|全县|全县|实现|达到|完成|约为|为|是|同比|比上年|较上年|"
    r"初步核算|经初步核算|经核算|据统计|数据显示|分产业看|增长|下降|上升)+"
)
_STRONG_BREAK = re.compile(r"[。；;！？!?\n]")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_VALUE_WINDOW = 40
_ALIASES = (
    (re.compile(r"(?<!第)一产"), "第一产业"),
    (re.compile(r"(?<!第)二产"), "第二产业"),
    (re.compile(r"(?<!第)三产"), "第三产业"),
    (re.compile(r"规上"), "规模以上"),
)


def _canonicalize(value: str) -> str:
    for pattern, replacement in _ALIASES:
        value = pattern.sub(replacement, value)
    return value


def normalize_measure(text: str) -> str:
    """Normalize a measure phrase while keeping the subject and predicate."""
    value = _MARKDOWN.sub("", text or "")
    value = _UNITS.sub("", value)
    value = _DIGITS.sub("", value)
    value = _PUNCT.sub("", value)
    value = _WS.sub("", value)
    value = _LEADING.sub("", value)
    return _canonicalize(value.lower())


def derive_measure_key(
    statement: str,
    *,
    chunk_text: str = "",
    value: str = "",
) -> str:
    """Derive a fine-grained measure key from statement and source context.

    When the statement is a fragment (for example ``增长4.3%``), the text before
    the value in the source chunk supplies the missing subject. The window is cut
    at the nearest strong sentence boundary so a previous measure is not merged.
    """
    base = statement or ""
    statement_key = normalize_measure(statement)
    if len(statement_key) >= 4:
        return statement_key
    if value and chunk_text:
        index = chunk_text.find(value)
        if index != -1:
            start = max(0, index - _VALUE_WINDOW)
            window = chunk_text[start:index]
            breaks = list(_STRONG_BREAK.finditer(window))
            if breaks:
                window = window[breaks[-1].end() :]
            if len(normalize_measure(window)) >= 2:
                base = window
    key = normalize_measure(base)
    if len(key) < 2:
        key = statement_key
    return key


def data_years(text: str) -> list[str]:
    """Explicit candidate data years excluding labelled publication/retrieval dates."""
    years = []
    for match in _YEAR.finditer(text or ''):
        prefix = text[max(0, match.start() - 16):match.start()]
        suffix = text[match.end():match.end() + 24]
        if re.search(r'(?:发布|公布|更新|上传|抓取)(?:日期|时间)?[：:\s]*$', prefix):
            continue
        if re.match(r'年(?:\d{1,2}月(?:\d{1,2}日)?)?\s*(?:发布|公布|更新|上传|抓取)', suffix):
            continue
        years.append(match.group())
    return years


def infer_period(
    statement: str,
    *,
    chunk_text: str = "",
    value: str = "",
    title: str = "",
    published_at: object | None = None,
    content_prefix: str = "",
) -> str:
    """Infer the observation year when the extractor left it empty.

    Only explicit data years and a statistical bulletin's reporting year qualify.
    Publication/retrieval dates and arbitrary header/title years are not data years.
    ``published_at`` stays accepted for caller compatibility, but is not evidence.
    """
    years = data_years(statement)
    if len(set(years)) == 1:
        return years[0]
    if len(set(years)) > 1:
        return ''
    if value and chunk_text:
        matches = list(re.finditer(r'(?<![\d.])' + re.escape(value) + r'(?![\d.])', chunk_text))
        candidates: set[str] = set()
        for match in matches:
            index = match.start()
            window = chunk_text[max(0, index - _VALUE_WINDOW) : match.end()]
            years = data_years(window)
            if len(set(years)) == 1 and not re.search(r'发布|更新|上传|抓取', window):
                candidates.add(years[0])
            elif len(set(years)) > 1:
                return ''
        if len(candidates) > 1:
            return ''
        if candidates:
            return next(iter(candidates))
    report_years = re.findall(r'((?:19|20)\d{2})年[^\d。\n]{0,40}统计公报', title or '')
    report_years = [year for year in report_years if year in data_years(title)]
    return report_years[0] if len(set(report_years)) == 1 else ''


def infer_claim_period(
    statement: str,
    *,
    chunk_text: str = "",
    value: str = "",
    title: str = "",
    published_at: object | None = None,
    content_prefix: str = "",
    document_year: str = "",
) -> str:
    """Resolve a claim's data period without borrowing the publication year.

    Claim-local years take priority. A claim that names several years stays a
    span (for example ``2024-2025``) and is never collapsed to one year or to
    the document year. The document year is only used when the claim, its
    title, and its evidence chunk mention no year at all; if a year was named
    but could not be resolved unambiguously, the period stays empty.
    """
    statement_years = sorted(set(data_years(statement)))
    if len(statement_years) > 1:
        return "-".join(statement_years)
    period = infer_period(
        statement,
        chunk_text=chunk_text,
        value=value,
        title=title,
        published_at=published_at,
        content_prefix=content_prefix,
    )
    if period:
        return period
    if statement_years:
        return statement_years[0]
    # A year was named but rejected as a publication label (or left ambiguous):
    # do not replace it with the document year.
    if any(_YEAR.search(text or "") for text in (statement, title, chunk_text)):
        return ""
    return str(document_year or "").strip()
