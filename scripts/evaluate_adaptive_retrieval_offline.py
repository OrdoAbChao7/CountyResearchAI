"""Replay saved raw search archives against legacy and slot-aware ranking; no network calls."""
from __future__ import annotations

import json
from pathlib import Path

from county_research_ai.models import RawDoc
from county_research_ai.search.adaptive_retrieval import rank_documents_for_slot
from county_research_ai.search.content_extractor import rerank_documents
from county_research_ai.search.query_engine import QueryEngine

CASES = (
    ("snapshot", "临泽县", "特色产业", Path("experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/continuation_matched_budget_deepseek_flash_20261019_region_06_snapshot_r1_C/data/raw/临泽县/20261018/raw_docs.json")),
    ("rise-fall", "临泽县", "产业兴衰", Path("experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/continuation_matched_budget_deepseek_flash_20261019_region_06_rise-fall_r1_C/data/raw/临泽县/20261018/raw_docs.json")),
    ("long-history", "于都县", "长周期兴衰史", Path("experiments/independent_comparison/runs/continuation_matched_budget_deepseek_flash_20261019/continuation_matched_budget_deepseek_flash_20261019_region_03_long-history_r1_C/data/raw/于都县/20261018/raw_docs.json")),
)


def load_docs(path: Path) -> list[RawDoc]:
    records = json.loads(path.read_text(encoding="utf-8"))
    docs = []
    for row in records:
        metadata = row.get("metadata") or {}
        raw_result = metadata.get("raw_result") or {}
        docs.append(RawDoc(
            title=row.get("title", ""),
            url=row.get("url", ""),
            snippet=row.get("snippet", ""),
            content=row.get("content") or raw_result.get("summary", ""),
            source=row.get("source", ""),
            metadata=metadata,
            published_at=row.get("published_at"),
            domain_type=row.get("domain_type", "unknown"),
            credibility_score=row.get("credibility_score", 0.5),
        ))
    return docs


def slot_metric_recall(docs: list[RawDoc], metrics: list[str]) -> float:
    text = "\n".join(f"{doc.title}\n{doc.snippet}\n{doc.content}" for doc in docs)
    return sum(metric in text for metric in metrics) / len(metrics) if metrics else 0.0


def main() -> None:
    engine = QueryEngine()
    rows = []
    for mode, county, focus, path in CASES:
        docs = load_docs(path)
        spec = engine.generate_research_spec(county, focus, mode)
        query_by_slot = {}
        for query in engine.generate_research_queries(county, focus, mode, max_queries=12):
            query_by_slot.setdefault(query.slot_id, query.query)
        legacy_hits = adaptive_hits = 0.0
        compared = 0
        for slot in spec.question_slots:
            query = query_by_slot.get(slot.slot_id, f"{county} {focus} {' '.join(slot.required_metrics)}")
            legacy = rerank_documents(list(docs), keywords=[query], county=county, top_k=3)
            adaptive = rank_documents_for_slot(list(docs), slot, query=query)[:3]
            legacy_hits += slot_metric_recall(legacy, slot.required_metrics)
            adaptive_hits += slot_metric_recall([item.document for item in adaptive], slot.required_metrics)
            compared += 1
        rows.append({
            "mode": mode,
            "region": county,
            "archive": str(path),
            "documents": len(docs),
            "slots": compared,
            "legacy_top3_metric_recall": round(legacy_hits / compared, 4),
            "adaptive_top3_metric_recall": round(adaptive_hits / compared, 4),
        })
    print(json.dumps({"offline_only": True, "cases": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
