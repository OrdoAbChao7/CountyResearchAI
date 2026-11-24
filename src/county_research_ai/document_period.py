"""Reporting periods used to identify annual bulletins during deduplication."""
from __future__ import annotations

import re

from .evidence.measure import infer_period

_BULLETIN_YEAR_SUFFIX = re.compile(r"统计公报\s*[(（]\s*((?:19|20)[0-9]{2})\s*年度?\s*[)）]")


def bulletin_reporting_year(title: str) -> str:
    """Read the reporting year from an explicit bulletin title."""
    if "统计公报" not in title:
        return ""
    years = set(_BULLETIN_YEAR_SUFFIX.findall(title))
    prefix_year = infer_period("", title=title)
    if prefix_year:
        years.add(prefix_year)
    return years.pop() if len(years) == 1 else ""


def document_year_key(title: str) -> str:
    """Keep dated title variants separate during document deduplication."""
    return bulletin_reporting_year(title) or ",".join(
        sorted(set(re.findall(r"(?<!\d)((?:19|20)\d{2})\s*年", title)))
    )
