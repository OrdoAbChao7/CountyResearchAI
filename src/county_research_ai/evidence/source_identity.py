"""Conservative evidence-origin groups, with auditable URL/content equivalences.

Equal nonempty text is evidence of duplication, never proof of independence.
Paraphrased reposts are outside this deterministic rule.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def source_groups(sources: Iterable[Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for source in sources:
        content = source.content or ''
        if not content.strip():
            continue
        url = source.canonical_url or ''
        parts = urlsplit(url)
        url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                          parts.query, ''))
        content_hash = hashlib.sha256(' '.join(content.split()).encode()).hexdigest()
        sid = getattr(source, 'snapshot_id', None) or getattr(source, 'doc_id', '')
        row = dict(source_ids={sid}, urls={url} if url else set(),
                   content_hashes={content_hash}, bases=set())
        matched = [g for g in groups if g['urls'] & row['urls']
                   or content_hash in g['content_hashes']]
        for group in matched:
            if group['urls'] & row['urls']:
                row['bases'].add('same_canonical_url')
            if group['content_hashes'] & row['content_hashes']:
                row['bases'].add('same_normalized_content')
            for key in row:
                row[key].update(group[key])
            groups.remove(group)
        groups.append(row)
    return [{key: sorted(value) for key, value in group.items()} for group in groups]
