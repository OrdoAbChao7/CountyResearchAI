from __future__ import annotations

import pytest

from county_research_ai.search.lexical import (
    BM25Index,
    LexicalDocument,
    dedupe_documents,
    recall_at_k,
    tokenize,
)

DOCS = [
    LexicalDocument(
        doc_id="gdp",
        text="德清县2024年地区生产总值为722.5亿元，同比增长5.8%。",
        canonical_url="https://a.gov.cn/stat",
    ),
    LexicalDocument(
        doc_id="industry",
        text="德清县规模以上工业增加值300.6亿元，同比增长7.7%。",
        canonical_url="https://b.gov.cn/industry",
    ),
    LexicalDocument(
        doc_id="tourism",
        text="德清县乡村旅游接待游客1200万人次，旅游收入增长明显。",
        canonical_url="https://c.gov.cn/tourism",
    ),
]


def _index(documents=None) -> BM25Index:
    index = BM25Index()
    index.add_many(list(documents if documents is not None else DOCS))
    return index


def test_tokenize_handles_cjk_bigrams_and_ascii_words():
    tokens = tokenize("德清县 GDP 722.5亿元")

    assert "德清" in tokens
    assert "清县" in tokens
    assert "gdp" in tokens
    assert "722.5" in tokens


def test_query_ranks_matching_document_first():
    hits = _index().query("地区生产总值 722.5亿元", top_k=3)

    assert hits[0].doc_id == "gdp"
    assert hits[0].score > 0
    assert "生产" in hits[0].matched_terms
    assert {hit.doc_id for hit in hits[1:]} <= {"industry", "tourism"}


def test_unrelated_query_returns_no_results_as_negative_control():
    hits = _index().query("quantum entanglement photonic lattice")

    assert hits == []


def test_metric_term_changes_ranking_as_negative_control():
    index = _index()

    gdp_hits = index.query("地区生产总值", top_k=1)
    industry_hits = index.query("规模以上工业增加值", top_k=1)

    assert gdp_hits[0].doc_id == "gdp"
    assert industry_hits[0].doc_id == "industry"


def test_empty_query_and_empty_index_return_nothing():
    assert _index().query("   ") == []
    assert BM25Index().query("德清县") == []


def test_top_k_is_respected_and_ties_are_deterministic():
    hits = _index().query("德清县", top_k=2)

    assert len(hits) == 2
    again = _index().query("德清县", top_k=2)
    assert [hit.doc_id for hit in hits] == [hit.doc_id for hit in again]


def test_duplicate_canonical_urls_are_dropped_not_counted_as_sources():
    duplicate = LexicalDocument(
        doc_id="gdp-repost",
        text=DOCS[0].text,
        canonical_url="https://a.gov.cn/stat?utm_source=wechat",
    )

    result = dedupe_documents([DOCS[0], duplicate, DOCS[1]])

    assert [document.doc_id for document in result.documents] == ["gdp", "industry"]
    assert result.duplicate_of == {"gdp-repost": "gdp"}


def test_duplicate_document_ids_are_rejected():
    index = BM25Index()
    index.add(DOCS[0])

    with pytest.raises(ValueError, match="duplicate document id"):
        index.add(DOCS[0])


def test_recall_at_k_uses_numerator_and_denominator():
    assert recall_at_k(["a", "b", "c"], {"a", "c", "d"}, k=3) == pytest.approx(2 / 3)
    assert recall_at_k(["a", "b", "c"], {"a", "c", "d"}, k=1) == pytest.approx(1 / 3)
    assert recall_at_k([], {"a"}, k=5) == 0.0
    with pytest.raises(ValueError):
        recall_at_k(["a"], set(), k=1)


def test_index_fingerprint_is_stable():
    assert _index().fingerprint() == _index().fingerprint()
    assert _index().fingerprint() != _index([DOCS[0]]).fingerprint()
