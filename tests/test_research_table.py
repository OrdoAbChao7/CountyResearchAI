"""Synthetic safety cases; never used as extraction input."""
import pytest

from county_research_ai.research_table.store import ResearchTable, compare


def package(value='100', period='2022', scope='county', text=None, url='local:a'):
    text = text or f'{period} output {value}'
    return {'project': 'test', 'source': {'canonical_url': url, 'content': text},
            'facts': [dict(region_id='330523', metric_id='output', original_name='output',
                           value=value, unit='亿元', period=period, scope=scope,
                           caliber='all', price_basis='current', excerpt=text, start=0)]}


def confirmed(db, p):
    fid = db.ingest(p)['facts'][0]
    db.review(fid, 'confirm', 'tester', 'checked original')
    return fid


def test_idempotence_history_and_conflict(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    b = confirmed(db, package('110', '2023', url='local:b'))
    calc = db.calculate(a, b, 'report.md#growth')
    assert db.ingest(package())['facts'] == []
    assert db.status(a) == 'confirmed'
    revision = db.ingest(package('101'))
    c = revision['facts'][0]
    assert db.status(a) == 'needs_review'
    assert db.status(b) == 'confirmed'
    assert db.status(c) == 'unverified'
    assert db.affected()[0]['id'] == calc
    with pytest.raises(ValueError):
        db.review(c, 'confirm', 'tester', 'newer publication')
    db.review(c, 'confirm', 'tester', 'explicit correction checked', supersedes=[a])
    assert db.status(c) == 'confirmed'
    assert db.status(a) == 'superseded'
    assert len(db.rows('sources')) == 3


def test_correction_and_repost(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    c = db.correct(a, {'value': '99'}, 'tester', 'transcription correction')
    db.review(c, 'confirm', 'tester', 'checked', supersedes=[a])
    db.ingest(package())
    assert db.fact(c)['value'] == '99'
    assert db.status(c) == 'confirmed'
    assert db.ingest(package(url='local:repost'))['facts'] == []
    assert db.rows('relations')[0]['basis'] == 'exact_content_hash'
    db.review(c, 'revoke', 'tester', 'recheck')
    assert db.status(c) == 'needs_review'


def test_unknown_scope_units_and_period(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    b = confirmed(db, package('110', '2023', scope='park', url='local:b'))
    assert compare(db.fact(a), db.fact(b))[0] == 'incomparable'
    with pytest.raises(ValueError):
        db.calculate(a, b, 'report')
    p = package(None, 'unknown', url='local:c')
    del p['facts'][0]['caliber']
    c = db.ingest(p)['facts'][0]
    assert db.fact(c)['value'] is None
    assert db.fact(c)['caliber'] == 'unknown'
    assert compare(db.fact(c), db.fact(c))[0] == 'insufficient'
    x = dict(db.fact(a), unit='万元', value='1000000')
    assert compare(db.fact(a), x)[0] == 'conditional'
    z = confirmed(db, package('0', '2021', url='local:z'))
    with pytest.raises(ValueError):
        db.calculate(z, a, 'report')


def test_atomic_validation_and_evidence(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    p = package()
    p['facts'].append(dict(p['facts'][0], excerpt='not in document'))
    with pytest.raises(ValueError):
        db.ingest(p)
    assert db.rows('facts') == []
    assert db.rows('sources') == []


def test_complete_impact_and_unaffected_pending(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    b = confirmed(db, package('110', '2023', url='local:b'))
    c = confirmed(db, package('120', '2024', url='local:c'))
    ab = db.calculate(a, b, 'report#2023')
    bc = db.calculate(b, c, 'report#2024')
    text = db.link_text([a], 'report#conclusion')
    db.review(a, 'revoke', 'tester', 'check again')
    assert {r['id'] for r in db.affected()} == {ab, text}
    assert bc not in {r['id'] for r in db.affected()}
    assert db.pending() == [a]
    assert db.reproduce(ab)['reproduced_value'] == db.reproduce(ab)['value']
    db.export(tmp_path / 'out')
    assert (tmp_path / 'out/facts.csv').is_file()
    assert (tmp_path / 'out/evidence.json').is_file()


def test_same_value_changed_source_requires_review_and_no_period_guess(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    p = package(text='2022 output 100 updated explanatory note')
    b = db.ingest(p)['facts'][0]
    assert db.status(a) == 'needs_review'
    assert db.status(b) == 'unverified'
    assert db.fact(a)['source_id'] != db.fact(b)['source_id']
    assert db.ingest(p)['facts'] == []


def test_extraction_uses_data_year_not_publication():
    from county_research_ai.research_table.extract import bamboo_candidates
    facts = bamboo_candidates('2022年全县竹产业总产值约166亿元，同比增长约7.7%。2024年发布', '330523')
    assert len(facts) == 2
    assert {f['period'] for f in facts} == {'2022'}
    assert all(f['caliber'] == 'unknown' for f in facts)
    assert bamboo_candidates('今年产值为零', '330523') == []


def test_period_correction_can_supersede_parent(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    b = db.correct(a, {'period': '2021'}, 'tester', 'wrong data year transcription')
    db.review(b, 'confirm', 'tester', 'checked original year', supersedes=[a])
    assert db.status(a) == 'superseded'
    assert db.fact(a)['period'] == '2022'
    assert db.fact(b)['period'] == '2021'


@pytest.mark.parametrize('field,value', [('metric_id', 'revenue'), ('scope', 'park'),
    ('caliber', 'above_designated_size'), ('price_basis', 'constant')])
def test_never_mix_different_definitions(field, value):
    a = dict(region_id='330523', metric_id='output', scope='county', caliber='all',
             price_basis='current', unit='亿元')
    assert compare(a, dict(a, **{field:value}))[0] == 'incomparable'


def test_supported_conversion_and_nonconsecutive_period(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    p = package('1100000', '2023', url='local:b')
    p['facts'][0]['unit'] = '万元'
    b = confirmed(db, p)
    result = db.reproduce(db.calculate(a, b, 'report#converted'))
    assert result['value'] == '10.0'
    c = confirmed(db, package('120', '2025', url='local:c'))
    with pytest.raises(ValueError):
        db.calculate(a, c, 'report#invalid-period')


def test_cli_and_reopen(tmp_path, capsys):
    import json

    from county_research_ai.research_table.__main__ import main
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(package()), encoding='utf-8')
    args = ['--db', str(tmp_path/'cli.db')]
    assert main(args+['import', str(path)]) == 0
    capsys.readouterr()
    assert main(args+['list']) == 0
    fid = json.loads(capsys.readouterr().out)[0]['id']
    assert main(args+['show', fid]) == 0
    assert main(args+['review', fid, 'confirm', '--actor', 'tester', '--reason', 'checked']) == 0
    assert main(args+['export', str(tmp_path/'export')]) == 0


def test_repost_then_original_replay_preserves_correction(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    a = confirmed(db, package())
    c = db.correct(a, {'value': '99'}, 'tester', 'checked correction')
    db.review(c, 'confirm', 'tester', 'checked', supersedes=[a])
    db.ingest(package(url='local:repost'))
    before = (len(db.rows('facts')), len(db.rows('reviews')), db.pending())
    assert db.ingest(package())['facts'] == []
    assert before == (len(db.rows('facts')), len(db.rows('reviews')), db.pending())
    assert db.status(c) == 'confirmed'


def test_crlf_archive_idempotence(tmp_path):
    db = ResearchTable(tmp_path / 'table.db')
    p = package(text='2022 output 100\r\nsecond line')
    db.ingest(p)
    assert db.ingest(p)['facts'] == []
