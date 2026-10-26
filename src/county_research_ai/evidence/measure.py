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

    Order: explicit statement year, year near the value, source title year,
    publication date, then the first year in the document header. Returns an
    empty string rather than inventing a year.
    """
    years = _YEAR.findall(statement or "")
    if years:
        return years[0]
    if value and chunk_text:
        index = chunk_text.find(value)
        if index != -1:
            window = chunk_text[max(0, index - _VALUE_WINDOW) : index + _VALUE_WINDOW]
            years = _YEAR.findall(window)
            if years:
                return years[0]
    years = _YEAR.findall(title or "")
    if years:
        return years[0]
    if published_at is not None:
        year = getattr(published_at, "year", None)
        if isinstance(year, int) and 1900 <= year <= 2099:
            return str(year)
    years = _YEAR.findall((content_prefix or "")[:800])
    return years[0] if years else ""
