"""Run with python -m county_research_ai.research_table; no provider initialization."""
import argparse
import json
import sys
from pathlib import Path

from .store import ResearchTable, encoded


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline research table v1')
    parser.add_argument('--db', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    load = commands.add_parser('import')
    load.add_argument('package', help='JSON package or array of packages')
    commands.add_parser('list')
    show = commands.add_parser('show')
    show.add_argument('fact_id')
    review = commands.add_parser('review')
    review.add_argument('fact_id')
    review.add_argument('action', choices=['confirm', 'revoke', 'conflict'])
    review.add_argument('--actor', required=True)
    review.add_argument('--reason', required=True)
    review.add_argument('--supersedes', nargs='*', default=[])
    correction = commands.add_parser('correct')
    correction.add_argument('fact_id')
    correction.add_argument('--changes', required=True, help='JSON object')
    correction.add_argument('--actor', required=True)
    correction.add_argument('--reason', required=True)
    calc = commands.add_parser('calculate')
    calc.add_argument('base')
    calc.add_argument('current')
    calc.add_argument('--location', required=True)
    text = commands.add_parser('link-text')
    text.add_argument('inputs', nargs='+')
    text.add_argument('--location', required=True)
    replay = commands.add_parser('reproduce')
    replay.add_argument('calculation_id')
    export = commands.add_parser('export')
    export.add_argument('directory')
    args = parser.parse_args(argv)
    db = ResearchTable(args.db)
    try:
        if args.command == 'import':
            packages = json.loads(Path(args.package).read_text(encoding='utf-8-sig'))
            if isinstance(packages, dict):
                packages = [packages]
            result = [db.ingest(p) for p in packages]
        elif args.command == 'list':
            result = [dict(f, verification_status=db.status(f['id'])) for f in db.rows('facts')]
        elif args.command == 'show':
            f = db.fact(args.fact_id)
            result = dict(fact=f, verification_status=db.status(args.fact_id),
                          source=next(s for s in db.rows('sources') if s['id'] == f['source_id']),
                          reviews=[r for r in db.rows('reviews') if r['fact_id'] == args.fact_id])
        elif args.command == 'review':
            db.review(args.fact_id, args.action, args.actor, args.reason, args.supersedes)
            result = {'status': db.status(args.fact_id)}
        elif args.command == 'correct':
            result = {'fact_id': db.correct(args.fact_id, json.loads(args.changes),
                                          args.actor, args.reason)}
        elif args.command == 'calculate':
            result = {'calculation_id': db.calculate(args.base, args.current, args.location)}
        elif args.command == 'link-text':
            result = {'output_id': db.link_text(args.inputs, args.location)}
        elif args.command == 'reproduce':
            result = db.reproduce(args.calculation_id)
        else:
            db.export(args.directory)
            result = {'directory': str(Path(args.directory).resolve())}
        print(encoded(result))
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
