"""Append-only evidence versions, review events and explicit calculation dependencies."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..domain.research_contracts import SourceDocument


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(obj):
    return hashlib.sha256(encoded(obj).encode('utf-8')).hexdigest()[:24]


def now():
    return datetime.now(timezone.utc).isoformat()


UNITS = {'元': ('money', Decimal(1)), '万元': ('money', Decimal(10000)),
         '亿元': ('money', Decimal(100000000)), '亩': ('area', Decimal(1)),
         '万亩': ('area', Decimal(10000)), '个': ('count', Decimal(1)),
         '万个': ('count', Decimal(10000))}
IDENTITY = ('project', 'region_id', 'metric_id', 'period')
CALIBER = ('scope', 'caliber', 'price_basis')


def compare(a, b):
    """Four-way result; periods are checked separately by each calculation."""
    keys = ('region_id', 'metric_id', *CALIBER, 'unit')
    if any(a.get(k) in (None, '', 'unknown') or b.get(k) in (None, '', 'unknown')
           for k in keys):
        return 'insufficient', 'unknown identity, scope, caliber, price basis or unit'
    if any(a[k] != b[k] for k in ('region_id', 'metric_id', *CALIBER)):
        return 'incomparable', 'different metric or statistical scope'
    if a['unit'] == b['unit']:
        return 'comparable', 'same definition and unit'
    x, y = UNITS.get(a['unit']), UNITS.get(b['unit'])
    if x and y and x[0] == y[0]:
        return 'conditional', 'convert via explicit unit factor v1'
    return 'incomparable', 'no conversion rule'


class ResearchTable:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.archive = self.path.parent / (self.path.stem + '_sources')
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise ValueError(f'unsupported schema: {version}')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS relations(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS calculations(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
          PRAGMA user_version=1;
        ''')

    def close(self):
        self.db.close()

    def rows(self, table):
        if table not in {'sources', 'facts', 'reviews', 'events', 'relations', 'calculations'}:
            raise ValueError('unknown table')
        return [json.loads(r['payload']) for r in self.db.execute(
            f'SELECT payload FROM {table} ORDER BY rowid')]

    def _insert(self, table, row):
        self.db.execute(f'INSERT OR IGNORE INTO {table}(id,payload) VALUES (?,?)',
                        (row['id'], encoded(row)))

    def fact(self, fid):
        row = self.db.execute('SELECT payload FROM facts WHERE id=?', (fid,)).fetchone()
        if row is None:
            raise ValueError(f'unknown fact: {fid}')
        return json.loads(row[0])

    def _event(self, kind, fid, related=None):
        item = dict(kind=kind, fact_id=fid, related=related or [])
        item['id'] = digest(item)
        item['created_at'] = now()
        self._insert('events', item)

    def status(self, fid):
        self.fact(fid)
        state = 'unverified'
        for r in self.rows('reviews'):
            if fid in r.get('supersedes', []):
                state = 'superseded'
            if r['fact_id'] == fid:
                state = {'confirm': 'confirmed', 'revoke': 'needs_review',
                         'conflict': 'conflict', 'invalidate': 'needs_review'}[r['action']]
        return state

    def _audit(self, fid, action, actor, reason, supersedes=()):
        f = self.fact(fid)
        r = dict(fact_id=fid, source_id=f['source_id'], action=action,
                 actor=actor, reason=reason, created_at=now(), supersedes=list(supersedes))
        self.db.execute('INSERT INTO reviews(payload) VALUES (?)', (encoded(r),))

    def _invalidate(self, fid, reason):
        if self.status(fid) == 'confirmed':
            self._audit(fid, 'invalidate', 'system', reason)
        self._event('needs_review', fid)

    def _prepare(self, raw, project, sid, content):
        f = {k: raw.get(k) or 'unknown' for k in
             ('region_id', 'metric_id', 'original_name', 'unit', 'period', *CALIBER,
              'qualifier')}
        if f['region_id'] == 'unknown' or f['metric_id'] == 'unknown':
            raise ValueError('stable region_id and metric_id required')
        if f['original_name'] not in ('unknown', f['metric_id']) and not raw.get('mapping_basis'):
            raise ValueError('alias mapping requires mapping_basis')
        value = raw.get('value')
        if value not in (None, '', 'unknown'):
            numeric = Decimal(str(value))
            if not numeric.is_finite():
                raise ValueError('non-finite value')
            value = str(numeric)
        else:
            value = None
        excerpt, start = raw['excerpt'], raw['start']
        if not excerpt or not isinstance(start, int) or start < 0:
            raise ValueError('exact excerpt and offset required')
        if content[start:start + len(excerpt)] != excerpt:
            raise ValueError('excerpt does not match archived source')
        f.update(project=project, source_id=sid, value=value, excerpt=excerpt,
                 start=start, end=start + len(excerpt),
                 mapping_basis=raw.get('mapping_basis', 'exact metric name'),
                 extraction_status=raw.get('extraction_status', 'manual_candidate'),
                 parent=raw.get('parent'))
        f['id'] = digest(f)
        f['created_at'] = now()
        return f

    def _archive_content(self, content_hash, content):
        self.archive.mkdir(parents=True, exist_ok=True)
        archive = self.archive / f'{content_hash}.txt'
        if archive.exists():
            if archive.read_bytes() != content.encode('utf-8'):
                raise ValueError('archive integrity failure')
        else:
            with archive.open('x', encoding='utf-8', newline='') as out:
                out.write(content)
        return archive

    def ingest(self, package):
        source = dict(package['source'])
        content = source.get('content') or ''
        url = source.get('canonical_url', source.get('url', ''))
        if not content or not url or not package.get('project'):
            raise ValueError('project, source URL and nonempty content required')
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        sid = hashlib.sha256(f'{url}\n{content_hash}'.encode()).hexdigest()[:24]
        # Reuse the existing source contract, retaining publication independently of period.
        doc = SourceDocument(doc_id=sid, canonical_url=url, content=content,
                             source_title=source.get('source_title', source.get('title', '')),
                             publish_date=source.get('publish_date', source.get('published_at')),
                             content_hash=content_hash, metadata=source.get('metadata', {}))
        facts = [self._prepare(f, package['project'], sid, content)
                 for f in package.get('facts', [])]
        project = package['project']
        old_sources = self.rows('sources')
        existing = next((s for s in old_sources if s['id'] == sid), None)
        prior_facts = self.rows('facts')
        # The earliest archived source owns identical evidence, including on replay.
        exact = next((s for s in old_sources if s['content_hash'] == content_hash), None)
        if exact and exact['id'] == sid:
            exact = None
        result = dict(source_id=sid, facts=[], duplicate=bool(existing or exact))
        archive = self._archive_content(content_hash, content)
        with self.db:
            s = doc.model_dump(mode='json')
            s.update(id=sid, archive=str(archive.resolve()), created_at=now())
            self._insert('sources', s)
            if exact:
                rel = dict(source_id=sid, related=exact['id'], basis='exact_content_hash')
                rel['id'] = digest(rel)
                self._insert('relations', rel)
            if result['duplicate']:
                self._event('duplicate_source', f'{project}:{sid}')
            # A replay may add previously unannotated facts. Exact reposts reuse original evidence.
            if exact:
                facts = [self._prepare(raw, project, exact['id'], content)
                         for raw in package.get('facts', [])]
            for f in facts:
                if any(old['id'] == f['id'] for old in prior_facts):
                    continue
                related = [o for o in prior_facts if all(o[k] == f[k] for k in IDENTITY)
                           and self.status(o['id']) != 'superseded']
                self._insert('facts', f)
                result['facts'].append(f['id'])
                kind = 'new_fact'
                for o in related:
                    comparison, _ = compare(o, f)
                    if comparison in ('incomparable', 'insufficient'):
                        kind = 'different_caliber' if comparison == 'incomparable' else 'insufficient'
                    elif not self._equal(o, f):
                        kind = 'revision_candidate'
                        self._event('unresolved_conflict', f['id'], [o['id']])
                        self._invalidate(o['id'], 'conflicting fact version')
                    else:
                        kind = 'duplicate_fact'
                        rel = dict(source_id=sid, related=o['source_id'],
                                   basis='same_fact_excerpt' if o['excerpt'] == f['excerpt']
                                   else 'same_value_not_independent_evidence')
                        rel['id'] = digest(rel)
                        self._insert('relations', rel)
                self._event(kind, f['id'], [o['id'] for o in related])
                if not related and any(all(o[k] == f[k] for k in IDENTITY[:-1])
                                       and o['period'] != f['period'] for o in prior_facts):
                    self._event('new_period', f['id'])
                prior_facts.append(f)
            if not existing and not exact:
                for o in prior_facts:
                    if o['source_id'] == sid:
                        continue
                    old_source = next(s for s in old_sources if s['id'] == o['source_id'])
                    if old_source['canonical_url'] == url and o['project'] == project:
                        if self.status(o['id']) != 'superseded':
                            self._invalidate(o['id'], 'source content version changed')
        return result

    @staticmethod
    def _equal(a, b):
        if a['value'] is None or b['value'] is None:
            return a['value'] == b['value'] and a['unit'] == b['unit']
        return ResearchTable._numeric(a) == ResearchTable._numeric(b)

    @staticmethod
    def _numeric(f):
        return Decimal(f['value']) * UNITS.get(f['unit'], ('same', Decimal(1)))[1]

    def conflicts(self, fid):
        f = self.fact(fid)
        return [o['id'] for o in self.rows('facts') if o['id'] != fid
                and self.status(o['id']) != 'superseded'
                and all(o[k] == f[k] for k in IDENTITY)
                and compare(o, f)[0] in ('comparable', 'conditional')
                and not self._equal(o, f)]

    def review(self, fid, action, actor, reason, supersedes=()):
        if action not in ('confirm', 'revoke', 'conflict') or not actor.strip() or not reason.strip():
            raise ValueError('action, reviewer and reason required')
        f = self.fact(fid)
        if self.status(fid) == 'superseded':
            raise ValueError('superseded versions cannot be reactivated; create a correction')
        for other in supersedes:
            o = self.fact(other)
            keys = IDENTITY[:-1] if f.get('parent') == other else IDENTITY
            if other == fid or any(o[k] != f[k] for k in keys):
                raise ValueError('supersedes must target the same fact identity')
        if action == 'confirm' and set(self.conflicts(fid)) - set(supersedes):
            raise ValueError('resolve conflicts explicitly with supersedes')
        with self.db:
            self._audit(fid, action, actor, reason, supersedes if action == 'confirm' else ())
            if action != 'confirm':
                self._event('needs_review', fid)

    def correct(self, fid, changes, actor, reason):
        allowed = {'value', 'unit', 'period', 'scope', 'caliber', 'price_basis',
                   'original_name', 'mapping_basis', 'qualifier', 'excerpt', 'start'}
        if set(changes) - allowed or not actor.strip() or not reason.strip():
            raise ValueError('invalid correction or missing audit information')
        old = self.fact(fid)
        source = next(s for s in self.rows('sources') if s['id'] == old['source_id'])
        raw = dict(old, **changes)
        raw.update(parent=fid, extraction_status='human_corrected')
        f = self._prepare(raw, old['project'], old['source_id'], source['content'])
        with self.db:
            self._insert('facts', f)
            self._audit(f['id'], 'revoke', actor, reason)
            self._invalidate(fid, 'human correction candidate')
            self._event('human_correction', f['id'], [fid])
        return f['id']

    def calculate(self, base, current, location):
        a, b = self.fact(base), self.fact(current)
        if a['project'] != b['project'] or compare(a, b)[0] not in ('comparable', 'conditional'):
            raise ValueError('incomparable inputs')
        if not all(re.fullmatch(r'\d{4}', x['period']) for x in (a, b)):
            raise ValueError('annual periods required')
        if int(b['period']) != int(a['period']) + 1:
            raise ValueError('consecutive periods required')
        if any(self.status(x['id']) != 'confirmed' or self.conflicts(x['id'])
               or x['value'] is None for x in (a, b)):
            raise ValueError('confirmed, non-conflicting, nonmissing inputs required')
        if self._numeric(a) == 0:
            raise ValueError('zero denominator')
        row = dict(formula='(current/base-1)*100', formula_version='growth_v1',
                   inputs=[base, current], location=location,
                   value=str((self._numeric(b) / self._numeric(a) - 1) * 100), unit='%',
                   qualifier='approximate' if any(x['qualifier'] != 'unknown' for x in (a,b))
                   else 'unknown')
        row['id'] = digest(row)
        row['created_at'] = now()
        with self.db:
            self._insert('calculations', row)
        return row['id']

    def affected(self):
        return [c for c in self.rows('calculations')
                if any(self.status(fid) != 'confirmed' or self.conflicts(fid)
                       for fid in c['inputs'])]

    def link_text(self, inputs, location):
        if not inputs or not location.strip():
            raise ValueError('fact versions and output location required')
        for fid in inputs:
            self.fact(fid)
        row = dict(formula='text_reference', formula_version='text_v1',
                   inputs=list(inputs), location=location, value=None, unit='unknown')
        row['id'] = digest(row)
        row['created_at'] = now()
        with self.db:
            self._insert('calculations', row)
        return row['id']

    def reproduce(self, calculation_id):
        c = next(c for c in self.rows('calculations') if c['id'] == calculation_id)
        if c['formula_version'] != 'growth_v1':
            return dict(c, reproduced_value=None)
        a, b = [self.fact(fid) for fid in c['inputs']]
        return dict(c, reproduced_value=str((self._numeric(b) / self._numeric(a) - 1) * 100))

    def pending(self):
        return [f['id'] for f in self.rows('facts')
                if self.status(f['id']) not in ('confirmed', 'superseded')]

    def export(self, directory):
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        sources = {s['id']: s for s in self.rows('sources')}
        rows = [dict(f, verification_status=self.status(f['id']),
                     publication_date=sources[f['source_id']]['publish_date'] or 'unknown',
                     source_url=sources[f['source_id']]['canonical_url'])
                for f in self.rows('facts')]
        if rows:
            with (out / 'facts.csv').open('w', encoding='utf-8-sig', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows({k: ('unknown' if v is None else v) for k,v in r.items()}
                                for r in rows)
        evidence = dict(sources=list(sources.values()), reviews=self.rows('reviews'),
                        relations=self.rows('relations'), pending=self.pending(),
                        calculations=self.rows('calculations'), affected=self.affected(),
                        unresolved_conflicts={f['id']: self.conflicts(f['id']) for f in rows
                                              if self.status(f['id']) != 'superseded'
                                              and self.conflicts(f['id'])})
        (out / 'evidence.json').write_text(encoded(evidence), encoding='utf-8')
        lines = ['# 增量更新报告', '', '历史事件保留；待办仅反映当前未确认状态。',
                 '', '## 历史变更事件（已解决事件不代表当前冲突）', '']
        for event in self.rows('events'):
            lines.append(f"- {event['kind']}: {event['fact_id']} related={event['related']}")
        lines.extend(['', '## 当前未解决冲突',
                      *[f'- {fid}: {others}' for fid, others in evidence['unresolved_conflicts'].items()],
                      '', '## 当前待复核', *[f'- {fid}' for fid in self.pending()],
                      '', '## 受影响计算和文字输出（禁止自动确认）'])
        lines.extend(f"- {c['id']} → {c['location']} inputs={c['inputs']}" for c in self.affected())
        (out / 'update.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
