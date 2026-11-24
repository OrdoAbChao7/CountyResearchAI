"""Regression coverage for title matching shortcuts and argument order."""
from difflib import SequenceMatcher

import pytest

from county_research_ai import processor as processor_module
from county_research_ai.models import RawDoc
from county_research_ai.processor import DocumentProcessor


def documents(*titles):
    return [RawDoc(title=title, url=f"https://example.com/{i}") for i, title in enumerate(titles)]


def test_disjoint_titles_skip_expensive_matching(monkeypatch):
    calls = []

    class CountingMatcher(SequenceMatcher):
        def ratio(self):
            calls.append((self.a, self.b))
            return super().ratio()

    monkeypatch.setattr(processor_module, "SequenceMatcher", CountingMatcher)
    docs = documents("a" * 20, "z" * 20)
    assert DocumentProcessor().deduplicate(docs) == docs
    assert calls == []


def test_similarity_uses_incoming_title_direction():
    """ratio() is asymmetric; dedup must compare (incoming title, seen title)."""
    first = "acbaaddacccbcbccbcac"
    second = "aababddacccbcbccbcac"
    assert SequenceMatcher(None, second, first).ratio() == 0.85
    assert SequenceMatcher(None, first, second).ratio() == 0.9

    docs = documents(first, second)
    assert DocumentProcessor().deduplicate(docs) == docs


@pytest.mark.parametrize("titles", [
    ("identical", "identical"),
    ("a" * 17, "a" * 17 + "b" * 6),  # Exactly 0.85 must be retained.
    ("安吉县竹产业产值突破百亿", "安吉县竹产业产值突破百亿元大关"),
    ("acbaaddacccbcbccbcac", "aababddacccbcbccbcac"),
    ("aababddacccbcbccbcac", "acbaaddacccbcbccbcac"),
])
def test_shortcuts_preserve_similarity_threshold(titles):
    docs = documents(*titles)
    expected = docs[:1] if SequenceMatcher(None, titles[1], titles[0]).ratio() > 0.85 else docs
    assert DocumentProcessor().deduplicate(docs) == expected
