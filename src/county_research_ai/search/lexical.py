"""Deterministic query-aware lexical baseline (BM25) for offline evaluation.

This is intentionally a small, dependency-free baseline. It exists so retrieval
quality can be measured against something reproducible before any dense or
provider-backed path is introduced. Tokenization handles CJK bigrams and ASCII
words; documents are deduplicated by canonical URL or content fingerprint.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .content_extractor import calculate_content_fingerprint, normalize_url

_WORD_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", re.IGNORECASE)
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]+")


def tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese/ASCII text deterministically."""
    lowered = text.lower()
    tokens = _WORD_RE.findall(lowered)
    for run in _CJK_RE.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


@dataclass(frozen=True)
class LexicalDocument:
    doc_id: str
    text: str
    canonical_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        fingerprint = calculate_content_fingerprint(self.text)
        if fingerprint:
            return fingerprint
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LexicalHit:
    doc_id: str
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class DedupeResult:
    documents: tuple[LexicalDocument, ...]
    duplicate_of: dict[str, str]


def _dedupe_key(document: LexicalDocument) -> str:
    if document.canonical_url:
        return f"url:{normalize_url(document.canonical_url)}"
    return f"content:{document.fingerprint}"


def dedupe_documents(documents: list[LexicalDocument]) -> DedupeResult:
    """Keep the first document per canonical URL/content fingerprint."""
    kept: list[LexicalDocument] = []
    duplicate_of: dict[str, str] = {}
    seen: dict[str, str] = {}
    for document in documents:
        key = _dedupe_key(document)
        if key in seen:
            duplicate_of[document.doc_id] = seen[key]
            continue
        seen[key] = document.doc_id
        kept.append(document)
    return DedupeResult(documents=tuple(kept), duplicate_of=duplicate_of)


class BM25Index:
    """Minimal BM25 index with deterministic tie-breaking."""

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self.k1 = k1
        self.b = b
        self._documents: dict[str, LexicalDocument] = {}
        self._term_frequencies: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}
        self._document_frequency: Counter[str] = Counter()
        self._total_length = 0

    def __len__(self) -> int:
        return len(self._documents)

    @property
    def documents(self) -> tuple[LexicalDocument, ...]:
        return tuple(self._documents.values())

    def add(self, document: LexicalDocument) -> None:
        if document.doc_id in self._documents:
            raise ValueError(f"duplicate document id: {document.doc_id}")
        tokens = tokenize(document.text)
        frequencies = Counter(tokens)
        self._documents[document.doc_id] = document
        self._term_frequencies[document.doc_id] = frequencies
        self._lengths[document.doc_id] = max(len(tokens), 1)
        self._total_length += len(tokens)
        self._document_frequency.update(frequencies.keys())

    def add_many(self, documents: list[LexicalDocument]) -> DedupeResult:
        result = dedupe_documents(documents)
        for document in result.documents:
            self.add(document)
        return result

    def _idf(self, term: str) -> float:
        total = len(self._documents)
        frequency = self._document_frequency.get(term, 0)
        if frequency == 0:
            return 0.0
        return math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))

    def query(self, text: str, *, top_k: int = 10) -> list[LexicalHit]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        query_terms = [term for term in tokenize(text) if term]
        if not query_terms or not self._documents:
            return []
        unique_terms = list(dict.fromkeys(query_terms))
        average_length = self._total_length / len(self._documents)
        scored: list[LexicalHit] = []
        for doc_id, frequencies in self._term_frequencies.items():
            length = self._lengths[doc_id]
            score = 0.0
            matched: list[str] = []
            for term in unique_terms:
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                matched.append(term)
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length / average_length
                )
                score += self._idf(term) * term_frequency * (self.k1 + 1) / denominator
            if matched:
                scored.append(
                    LexicalHit(
                        doc_id=doc_id,
                        score=round(score, 6),
                        matched_terms=tuple(matched),
                    )
                )
        scored.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return scored[:top_k]

    def fingerprint(self) -> str:
        """Stable digest of the indexed corpus for evaluation manifests."""
        digest = hashlib.sha256()
        for doc_id in sorted(self._documents):
            digest.update(doc_id.encode("utf-8"))
            digest.update(self._documents[doc_id].fingerprint.encode("utf-8"))
        return digest.hexdigest()


def recall_at_k(
    ranked_ids: list[str], relevant_ids: set[str], *, k: int
) -> float:
    """Fraction of relevant documents found in the first ``k`` results."""
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    top = set(ranked_ids[:k])
    return len(top & relevant_ids) / len(relevant_ids)
