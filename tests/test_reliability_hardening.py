"""Synthetic adversarial and positive controls for deterministic reliability."""
from datetime import datetime

import pytest

from county_research_ai.domain.research_contracts import AtomicClaim
from county_research_ai.evidence.graph import _claim_supported_by_quote
from county_research_ai.evidence.measure import infer_period


@pytest.mark.parametrize(('statement', 'quote', 'expected'), [
    ('预算收入下降3.5%', '2022年安吉县预算收入增长3.5%。', False),
    ('预算收入增长3.5%', '2022年安吉县预算收入下降3.5%。', False),
    ('预算收入增长3.5%', '2022年安吉县预算收入-3.5%。', False),
    ('预算收入下降3.5%', '2022年安吉县预算收入下降3.5%。', True),
    ('预算收入增长3.5%', '2022年安吉县预算收入增长3.5%。', True),
    ('预算收入增长3.5%', '2022年安吉县预算收入增长4%。用电量增长3.5%。', False),
    ('预算收入下降3.5%', '2022年安吉县预算收入增长3.5%，社保支出下降3.5%。', False),
    ('预算收入增长3.5%', '2022年安吉县预算收入增长3.5%，社保支出下降3.5%。', True),
    ('预算收入增长3.5%', '2022年安吉县预算收入100亿元，同比增长3.5%。', True),
])
def test_direction_and_measure_binding(statement, quote, expected):
    claim = AtomicClaim(claim_id='test', statement=statement, region_id='安吉县',
                        metric_id='预算收入', value='3.5', unit='%', period='2022')
    assert _claim_supported_by_quote(claim, quote) is expected


@pytest.mark.parametrize(('kwargs', 'expected'), [
    ({'published_at': datetime(2026, 1, 1)}, ''),
    ({'content_prefix': '发布日期：2026-01-01'}, ''),
    ({'title': '2026年发布的竹产业新闻'}, ''),
    ({'title': '2024年安吉县统计公报'}, '2024'),
    ({'chunk_text': '2024年全县产值100亿元。', 'value': '100'}, '2024'),
])
def test_observation_year_requires_data_evidence(kwargs, expected):
    assert infer_period('全县产值100亿元', **kwargs) == expected


def test_published_and_observed_times_remain_separate():
    from county_research_ai.evidence.ledger import build_evidence_ledger
    from county_research_ai.models import CountyInfo, ProcessedData, RawDoc
    doc = RawDoc(title='安吉县产业资料', url='local:test', content='全县竹产业产值100亿元。')
    processed = ProcessedData(county=CountyInfo.from_name('安吉县'), focus='竹产业', docs=[doc])
    ledger = build_evidence_ledger(processed)
    assert next(iter(ledger.sources.values())).publish_date is None


def test_reposted_sources_do_not_satisfy_independent_gate(tmp_path):
    from county_research_ai.api.evidence_service import persist_run_evidence, thresholds_met
    from county_research_ai.domain.research_contracts import ResearchContract, SourceDocument
    from county_research_ai.evidence.graph import EvidenceGraphStore
    from tests.test_api_evidence_service import CONTENT, _ledger, _slot

    ledger = _ledger()
    original = ledger.sources['snap-1']
    # Same text with a different URL is a repost; an unrelated document isn't support.
    ledger.add_source(original.model_copy(update={'doc_id': 'repost', 'canonical_url': 'local:repost', 'chunks': []}))
    ledger.add_source(SourceDocument(doc_id='irrelevant', canonical_url='local:irrelevant', content='其他地区资料'))
    pack = ledger.select_evidence_pack(_slot())
    pack.source_map.update(ledger.sources)
    graph = EvidenceGraphStore(tmp_path / 'graph.sqlite')
    summary = persist_run_evidence(graph, ledger, [pack], run_id='gate')
    assert summary['independent_sources'] == 1
    contract = ResearchContract(objective='test', regions=['德清县'], evidence_thresholds={'min_independent_sources': 2})
    assert thresholds_met(contract, summary)[0] is False
    assert CONTENT


def test_graph_reposts_have_one_support_origin(tmp_path):
    from county_research_ai.evidence.graph import EvidenceGraphStore
    from tests.test_evidence_graph import _claim, _ledger, _source
    source = _source('snap-1')
    repost = _source('snap-2', url='local:repost')
    claim = _claim('claim-1').model_copy(update={
        'source_ids': ['snap-1', 'snap-2'],
        'evidence_chunk_ids': ['snap-1:chunk:1', 'snap-2:chunk:1']})
    ledger = _ledger(source, claims=[claim])
    ledger.add_source(repost)
    graph = EvidenceGraphStore(tmp_path/'graph.sqlite')
    graph.save_ledger(ledger, run_id='test')
    checks = graph.get_chain('claim-1', run_id='test').verification.deterministic_checks
    assert checks['independent_support'] == 1


@pytest.mark.parametrize(('statement', 'value', 'quote', 'expected'), [
    ('预算收入下降3.5%', '3.5', '2022年安吉县预算收入-3.5%。', True),
    ('预算收入-3.5%', '-3.5', '2022年安吉县预算收入下降3.5%。', True),
    ('预算收入增长0%', '0', '2022年安吉县预算收入增长0%。', True),
    ('预算收入增长3.5%', '3.5', '2022年安吉县预算收入增长30.5%。', False),
    ('预算收入增长3.5%', '3.5', '2022年安吉县预算收入100亿元。增长3.5%。', False),
    ('预算收入增长3.5%', '3.5', '2022年安吉县预算收入增长4%。2023年预算收入增长3.5%。', False),
])
def test_signed_values_and_local_periods(statement, value, quote, expected):
    claim = AtomicClaim(claim_id='test', statement=statement, region_id='安吉县',
                        metric_id='预算收入', value=value, unit='%', period='2022')
    assert _claim_supported_by_quote(claim, quote) is expected


def test_source_groups_transitive_identity_and_empty_sources():
    from county_research_ai.domain.research_contracts import SourceDocument
    from county_research_ai.evidence.source_identity import source_groups
    docs = [SourceDocument(doc_id='a', canonical_url='local:a', content='first'),
            SourceDocument(doc_id='b', canonical_url='local:b', content='second'),
            SourceDocument(doc_id='c', canonical_url='local:a', content='second'),
            SourceDocument(doc_id='empty', canonical_url='local:empty')]
    groups = source_groups(docs)
    assert len(groups) == 1
    assert groups[0]['source_ids'] == ['a', 'b', 'c']


@pytest.mark.parametrize(('statement', 'quote', 'expected'), [
    ('预算收入增长3.5%', '2022年安吉县概况。预算收入增长3.5%（2023年）。', False),
    ('预算收入增长3.5%', '2022年安吉县非税预算收入增长3.5%。', False),
    ('预算收入增长3.5%', '2022年安吉县人均预算收入增长3.5%。', False),
    ('全县预算收入增长3.5%', '2022年安吉县预算收入增长3.5%。', True),
    ('预算收入增长3.5%', '2022年安吉县预算收入不增长3.5%。', False),
    ('预算收入增长3.5%', '2022年安吉县预算收入增长3.5%是错误数据，实际下降3.5%。', False),
])
def test_review_adversarial_and_scope_controls(statement, quote, expected):
    claim = AtomicClaim(claim_id='test', statement=statement, region_id='安吉县',
                        metric_id='预算收入', value='3.5', unit='%', period='2022')
    assert _claim_supported_by_quote(claim, quote) is expected


def test_publication_year_in_statement_is_not_a_data_year():
    assert infer_period('2026年发布的数据显示全县产值100亿元') == ''


def test_graph_counts_only_supporting_link_origins(tmp_path):
    from county_research_ai.evidence.graph import EvidenceGraphStore
    from tests.test_evidence_graph import _claim, _ledger, _source
    valid = _source('snap-1')
    irrelevant = _source('snap-2', url='local:other', content='德清县2024年居民消费价格上涨1%。')
    claim = _claim('test').model_copy(update={'source_ids':['snap-1','snap-2'],
        'evidence_chunk_ids':['snap-1:chunk:1','snap-2:chunk:1']})
    graph = EvidenceGraphStore(tmp_path/'graph.sqlite')
    graph.save_ledger(_ledger(valid, irrelevant, claims=[claim]), run_id='test')
    assert graph.get_chain('test', run_id='test').verification.deterministic_checks['independent_support'] == 1


def test_repeated_value_across_years_does_not_guess_first_year():
    assert infer_period('产值100亿元', chunk_text='2023年产值100亿元。2024年产值100亿元。', value='100') == ''


def test_multi_year_statement_does_not_use_title_as_tiebreaker():
    assert infer_period('2023年产值100亿元，2024年产值110亿元', title='2024年安吉县统计公报') == ''


def test_month_publication_date_does_not_infer_data_year():
    assert infer_period('2026年10月发布的数据显示预算收入增长3.5%') == ''


def test_publication_header_cannot_support_observation_year():
    claim = AtomicClaim(claim_id='test', statement='预算收入增长3.5%', region_id='安吉县',
                        metric_id='预算收入', value='3.5', unit='%', period='2026')
    assert not _claim_supported_by_quote(claim, '发布日期：2026年10月27日。安吉县预算收入增长3.5%。')


def test_region_and_scope_prefixes_are_normalized_symmetrically():
    quote = '2022年安吉县全县预算收入增长3.5%'
    claim = AtomicClaim(claim_id='test', statement=quote, region_id='安吉县',
                        metric_id='预算收入', value='3.5', unit='%', period='2022')
    assert _claim_supported_by_quote(claim, quote)

