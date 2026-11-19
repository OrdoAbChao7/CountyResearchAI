"""Claim ↔ Evidence support checks.

This module is the single place that decides whether a piece of evidence may
support a factual claim.  It deliberately separates two concerns that used to
be conflated:

* ``EvidenceItem.credibility_score`` describes the *source* (government,
  research, news, social ...).
* ``EvidenceItem.verification_status`` describes whether the *evidence item*
  itself has been verified (direct primary-source quote, complete metadata, or
  independent corroboration).
* A ``Claim`` may only be marked ``VERIFIED`` when every cited evidence item is
  itself verified **and** the claim text is lexically supported by that item.

The check is deterministic and intentionally conservative.  It is not a truth
oracle; it prevents an LLM from turning an arbitrary, unrelated or unverified
Evidence ID into a verified fact.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..models import EvidenceItem

_MIN_CLAIM_CHARS = 4
_NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|亿元|万元|万吨|万亩|万件|万斤|千吨|平方公里|公里|家|个|户|人|万人)?"
)
# Keep CJK characters, Latin letters and digits; drop punctuation/whitespace so
# n-gram overlap is not broken by formatting differences.
_NOISE_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")


def normalize_text(text: str) -> str:
    """Normalize text for deterministic lexical comparison."""
    return _NOISE_RE.sub("", (text or "").lower())


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def _numbers(text: str) -> set[str]:
    return {match.group(0).replace(" ", "") for match in _NUMBER_RE.finditer(text or "")}


def claim_supported_by_evidence(
    claim_text: str,
    evidence: EvidenceItem | None,
    *,
    require_verified: bool = True,
) -> bool:
    """Return True when *evidence* directly supports *claim_text*.

    A high source credibility score is never sufficient on its own.  If the
    claim contains a number, that number (including its unit) must appear in
    the evidence.  Otherwise the claim must share a distinctive 4-gram, or a
    sufficiently large share of character bigrams, with the evidence.
    """
    if evidence is None:
        return False
    if require_verified and evidence.verification_status != "verified":
        return False

    claim = normalize_text(claim_text)
    evidence_text = normalize_text(
        " ".join(part for part in (evidence.claim, evidence.snippet, evidence.title) if part)
    )
    if len(claim) < _MIN_CLAIM_CHARS or not evidence_text:
        return False

    claim_numbers = _numbers(claim_text)
    if claim_numbers:
        evidence_numbers = _numbers(
            " ".join(part for part in (evidence.claim, evidence.snippet, evidence.title) if part)
        )
        # A factual number that cannot be found in the cited evidence is not
        # supported, even if the surrounding prose overlaps.
        if not (claim_numbers & evidence_numbers):
            return False

    if _ngrams(claim, 4) & _ngrams(evidence_text, 4):
        return True

    claim_bigrams = _ngrams(claim, 2)
    if not claim_bigrams:
        return False
    overlap_ratio = len(claim_bigrams & _ngrams(evidence_text, 2)) / len(claim_bigrams)
    return overlap_ratio >= 0.4


@dataclass(frozen=True)
class ClaimEvidenceCheck:
    """Result of mapping a claim's cited IDs to actual evidence items."""

    requested: list[str]
    existing: list[str]
    supported: list[str]
    unknown: list[str]
    unsupported: list[str]

    @property
    def fully_supported(self) -> bool:
        return bool(self.existing) and not self.unknown and not self.unsupported

    @property
    def partially_supported(self) -> bool:
        return bool(self.supported) and (bool(self.unknown) or bool(self.unsupported))


def check_claim_evidence(
    claim_text: str,
    evidence_ids: list[str],
    lookup: Callable[[str], EvidenceItem | None],
) -> ClaimEvidenceCheck:
    """Validate cited evidence IDs and check whether each one supports the claim."""
    requested = [str(item) for item in evidence_ids if item]
    existing: list[str] = []
    supported: list[str] = []
    unknown: list[str] = []
    unsupported: list[str] = []
    for evidence_id in requested:
        item = lookup(evidence_id)
        if item is None:
            unknown.append(evidence_id)
            continue
        existing.append(evidence_id)
        if claim_supported_by_evidence(claim_text, item):
            supported.append(evidence_id)
        else:
            unsupported.append(evidence_id)
    return ClaimEvidenceCheck(
        requested=list(dict.fromkeys(requested)),
        existing=list(dict.fromkeys(existing)),
        supported=list(dict.fromkeys(supported)),
        unknown=list(dict.fromkeys(unknown)),
        unsupported=list(dict.fromkeys(unsupported)),
    )


__all__ = [
    "ClaimEvidenceCheck",
    "check_claim_evidence",
    "claim_supported_by_evidence",
    "normalize_text",
]
