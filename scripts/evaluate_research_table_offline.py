"""Two-round frozen synthetic replay followed by separately loaded gold scoring."""
import argparse
import hashlib
import json
from pathlib import Path

from county_research_ai.research_table.store import ResearchTable, encoded

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'experiments/research_table/synthetic_inputs'


def run(out):
    """No gold argument and no access to gold contents during execution."""
    db = ResearchTable(out / 'research.db')
    first = json.loads((INPUT / 'round1.json').read_text(encoding='utf-8'))
    second = json.loads((INPUT / 'round2.json').read_text(encoding='utf-8'))
    ids = []
    for p in first:
        fid = db.ingest(p)['facts'][0]
        db.review(fid, 'confirm', 'synthetic-review-replay', 'frozen manual confirmation')
        ids.append(fid)
    db.calculate(ids[0], ids[1], 'report#growth-anji')
    db.calculate(ids[2], ids[3], 'report#growth-unaffected')
    db.link_text([ids[0]], 'report#text-anji')
    first_values = [db.fact(fid)['value'] for fid in ids]
    db.export(out / 'round1')
    added = [db.ingest(p) for p in second]
    park = added[2]['facts'][0]
    db.review(park, 'confirm', 'synthetic-review-replay', 'distinct park scope')
    scope_error = 0
    try:
        db.calculate(ids[0], park, 'report#invalid-scope')
        scope_error += 1
    except ValueError:
        pass
    before = (len(db.rows('facts')), len(db.rows('reviews')), set(db.pending()))
    for p in second:
        db.ingest(p)
    after = (len(db.rows('facts')), len(db.rows('reviews')), set(db.pending()))
    confirmed = [f for f in db.rows('facts') if db.status(f['id']) == 'confirmed']
    sources = {s['id']: s for s in db.rows('sources')}
    traceable = sum(sources[f['source_id']]['content'][f['start']:f['end']] == f['excerpt']
                    for f in confirmed)
    observations = dict(affected=[c['location'] for c in db.affected()],
                        scope_errors=scope_error, scope_attempts=1,
                        confirmed=len(confirmed), traceable=traceable,
                        idempotent=before == after, first_values=first_values,
                        unaffected_pending=any(fid in db.pending() for fid in ids[2:]),
                        duplicate_repost_added_facts=len(added[3]['facts']),
                        synthetic=True, provider_calls=0, user_time_reduction=None)
    db.export(out / 'round2')
    db.close()
    (out / 'observations.json').write_text(encoded(observations), encoding='utf-8')
    return observations


def score(observed, gold):
    actual, expected = set(observed['affected']), set(gold['affected'])
    tp = len(actual & expected)
    precision = tp / len(actual) if actual else None
    recall = tp / len(expected) if expected else None
    return dict(impact_precision=precision, impact_recall=recall,
                impact_tp=tp, impact_fp=len(actual-expected), impact_fn=len(expected-actual),
                wrong_scope_calculations=observed['scope_errors'],
                scope_cases=observed['scope_attempts'],
                confirmed_traceability=observed['traceable'] / observed['confirmed'],
                confirmed_count=observed['confirmed'],
                input_value_fidelity=observed['first_values'] == gold['expected_values_round1'],
                idempotent=observed['idempotent'],
                unaffected_not_pending=not observed['unaffected_pending'],
                repost_no_new_facts=observed['duplicate_repost_added_facts'] == 0,
                product_benefit='NOT_VALIDATED', synthetic=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit('Use a new output directory')
    manifest = json.loads((INPUT / 'SHA256.json').read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((INPUT / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Frozen input changed: {name}')
    args.output.mkdir(parents=True)
    observed = run(args.output)
    # Score only AFTER import, review replay, exports and observation freeze have completed.
    gold = json.loads((INPUT / 'gold.json').read_text())
    result = score(observed, gold)
    (args.output / 'scores.json').write_text(encoded(result), encoding='utf-8')
    print(encoded(result))


if __name__ == '__main__':
    main()
