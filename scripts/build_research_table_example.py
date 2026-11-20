"""Freeze actual archived inputs and replay two rounds without network or gold labels."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from county_research_ai.research_table.extract import bamboo_candidates
from county_research_ai.research_table.store import ResearchTable, encoded

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    out = args.output
    if out.exists():
        raise SystemExit('Use a new output directory to preserve previous runs')
    out.mkdir(parents=True)
    frozen = ROOT / 'experiments/research_table/real_inputs'
    if not frozen.exists():
        raise SystemExit('Frozen inputs missing')
    manifest = json.loads((frozen / 'SHA256.json').read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((frozen / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Frozen input changed: {name}')
    table = ResearchTable(out / 'research.db')
    trace = []
    for round_id in (1, 2):
        packages = json.loads((frozen / f'round{round_id}.json').read_text(encoding='utf-8'))
        for package in packages:
            package['facts'] = bamboo_candidates(package['source']['content'], '330523')
            result = table.ingest(package)
            trace.append(result)
            # Demonstrates the review API, explicitly not a real user study or expert approval.
            for fid in result['facts']:
                table.review(fid, 'confirm', 'example-script',
                             '演示核查事件：规则摘录精确匹配；非真实研究人员签核，口径未知仍禁止计算')
        table.export(out / f'round{round_id}')
    (out / 'trace.json').write_text(encoded(trace), encoding='utf-8')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen.glob('*.json')}
    (out / 'input_hashes.json').write_text(encoded(hashes), encoding='utf-8')
    metrics = json.loads((ROOT / 'experiments/research_table/metric_dictionary.json').read_text(encoding='utf-8'))
    coverage_rows = []
    for year in ('2022', '2023', '2024', '2025'):
        for metric in metrics:
            hits = [f for f in table.rows('facts')
                    if f['period'] == year and f['metric_id'] == metric['metric_id']]
            coverage_rows.append(dict(region_id='330523', year=year,
                metric_id=metric['metric_id'], name=metric['name'],
                value=hits[0]['value'] if hits else 'unknown',
                status='observed_scope_unknown' if hits else 'missing'))
    with (out / 'coverage.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(coverage_rows[0]))
        writer.writeheader()
        writer.writerows(coverage_rows)
    coverage = {}
    for label, years in [('supported_period', ['2022', '2023']),
                         ('recent_three_years', ['2023', '2024', '2025'])]:
        cells = [r for r in coverage_rows if r['year'] in years]
        missing = sum(r['status'] == 'missing' for r in cells)
        coverage[label] = dict(years=years, regions=1, metrics=len(metrics), cells=len(cells),
                               missing=missing, missing_rate=missing / len(cells))
    (out / 'coverage.json').write_text(encoded(coverage), encoding='utf-8')
    table.close()
    print(out.resolve())


if __name__ == '__main__':
    main()
