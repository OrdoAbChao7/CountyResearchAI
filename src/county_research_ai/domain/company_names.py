"""Registered company names mentioned inside a Claim statement."""
from __future__ import annotations

import re

_COMPANY = re.compile(r"[一-龥]{2,40}?(?:股份有限公司|有限责任公司|有限公司)")
# Prepositions and verbs that introduce a name; none occurs inside the registered names seen so far.
_LEADING_PARTICLE = re.compile(r"^.*(?:的|在|位于|走进|到|至|给)")
_ADMIN_LEVEL = r"[一-龥]{1,4}?(?:省|市|县|区|镇|乡|街道)"
_ADMIN_CHAIN = re.compile(rf"(?:{_ADMIN_LEVEL})+")
_ADMIN_LEVEL_RE = re.compile(_ADMIN_LEVEL)


def _clean(name: str) -> str:
    name = _LEADING_PARTICLE.sub("", name)
    chain = _ADMIN_CHAIN.search(name)
    if chain is None:
        return name
    # Text before the first administrative name is a verb phrase, not part of the company.
    name = name[chain.start():]
    chain = _ADMIN_CHAIN.match(name)
    # A full address (province, city, county, town...) precedes the name. A single place name
    # such as 安吉县 may be the registered name's own first word, so it stays.
    if chain is not None and len(_ADMIN_LEVEL_RE.findall(chain.group())) >= 2:
        name = name[chain.end():]
    return name


def company_names(statement: str) -> list[str]:
    """Return company names with leading verbs and full addresses removed."""
    names: list[str] = []
    for match in _COMPANY.finditer(statement):
        name = _clean(match.group())
        if len(name) >= 6 and name not in names:
            names.append(name)
    return names
