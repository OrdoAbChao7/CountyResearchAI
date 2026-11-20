"""Non-destructive migration of existing RawDoc JSON into a new table database."""
import argparse
import json
from pathlib import Path

from county_research_ai.evidence.source_contract import serialize_source_documents
from county_research_ai.models import RawDoc
from county_research_ai.research_table.extract import bamboo_candidates
from county_research_ai.research_table.store import ResearchTable, encoded


def main():
    p = argparse.ArgumentParser()
    p.add_argument('archive', type=Path)
    p.add_argument('--db', required=True)
    p.add_argument('--project', required=True)
    p.add_argument('--region-id', required=True)
    args = p.parse_args()
    docs = [RawDoc(**d) for d in json.loads(args.archive.read_text(encoding='utf-8-sig'))]
    table = ResearchTable(args.db)
    results = []
    try:
        for source in serialize_source_documents(docs):
            if not source['content']:
                continue
            # Empty/unknown publication remains unknown; document_timestamp is not publication.
            results.append(table.ingest(dict(project=args.project, source=source,
                facts=bamboo_candidates(source['content'], args.region_id))))
        print(encoded(results))
    finally:
        table.close()


if __name__ == '__main__':
    main()
