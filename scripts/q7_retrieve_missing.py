"""Q7 bounded public-web retrieval recovery for missing GT facts.

For each fact, issue at most N region/metric/year queries, fetch at most M
results per query, and record whether the exact excerpt or value+metric+region
was recovered. Every fetched page is cached and hashed. This is a free public
web path, not a paid provider; it is still bounded and not comprehensive.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.diagnose_quality_funnel import GROUND_TRUTH, metric_tokens, norm, numbers_in

from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evidence.graph import _quote_contains_value
from county_research_ai.search.public_web import FreeWebClient

OUTPUT = Path("experiments/quality/20261026_q7_retrieval")
OFFICIAL_SUFFIXES = (".gov.cn", "news.cn", "people.com.cn", "xinhuanet.com")


def _queries(claim: GroundTruthClaim) -> list[str]:
    metric = re.sub(r"[（）()]", " ", claim.metric or "").strip()
    expanded = (
        metric.replace("一产", "第一产业")
        .replace("二产", "第二产业")
        .replace("三产", "第三产业")
    )
    year = claim.metric_year or ""
    region = claim.region
    bases = [f"{region} {metric} {year}".strip()]
    if expanded != metric:
        bases.append(f"{region} {expanded} {year}".strip())
    queries: list[str] = []
    for base in bases:
        queries.extend(
            [
                base,
                f"{base} 政府工作报告",
                f"{base} 统计公报",
                f"{base} 统计年鉴",
            ]
        )
    if year:
        digits = re.sub(r"\D", "", year)
        if digits and int(digits) < 2010:
            queries.append(f"{bases[0]} 地方志 志书")
    return list(dict.fromkeys(queries))


def _contains_year(text: str, year: str) -> bool:
    return bool(year and re.search(rf"(?<!\d){re.escape(year)}(?!\d)", text))


def _metric_aliases(claim: GroundTruthClaim) -> list[str]:
    tokens = metric_tokens(claim)
    aliases: list[str] = []
    for token in tokens:
        if len(token) > 30:
            continue
        candidates = [token]
        for old, new in (
            ("规模企业", "规模以上工业"),
            ("规模以上企业", "规模以上工业企业"),
            ("二产", "第二产业"),
            ("一产", "第一产业"),
            ("三产", "第三产业"),
        ):
            if old in token:
                candidates.append(token.replace(old, new))
        for candidate in list(candidates):
            for suffix in ("数量", "比重", "产值", "总额"):
                if candidate.endswith(suffix) and len(candidate) - len(suffix) >= 4:
                    candidates.append(candidate[: -len(suffix)])
        aliases.extend(candidates)
    return list(dict.fromkeys(aliases))


def score_page(claim: GroundTruthClaim, text: str, title: str, url: str) -> dict[str, Any]:
    excerpt = norm(claim.evidence_excerpt)
    expected = claim.expected_answer or claim.claim
    nums = numbers_in(expected, claim.unit)
    primary = nums[0] if nums else None
    haystack = f"{text}\n{title}\n{url}"
    excerpt_hit = bool(excerpt and len(excerpt) >= 8 and excerpt in norm(text))
    value_hit = bool(
        primary and _quote_contains_value(text, primary[0], primary[1])
    )
    metric_hit = any(alias and norm(alias) in norm(haystack) for alias in _metric_aliases(claim))
    region_hit = claim.region in haystack
    year_hit = _contains_year(haystack, claim.metric_year)
    score = (
        (10 if excerpt_hit else 0)
        + (5 if value_hit else 0)
        + (3 if metric_hit else 0)
        + (2 if region_hit else 0)
        + (1 if year_hit else 0)
    )
    year_ok = not claim.metric_year or year_hit
    exact_recovery = excerpt_hit and year_ok
    value_metric_recovery = value_hit and metric_hit and region_hit and year_ok
    value_context_recovery = value_hit and region_hit and year_hit and primary is not None
    hit = exact_recovery or value_metric_recovery
    host = urlparse(url).hostname or ""
    return {
        "excerpt_hit": excerpt_hit,
        "value_hit": value_hit,
        "metric_hit": metric_hit,
        "region_hit": region_hit,
        "year_hit": year_hit,
        "official": any(host.endswith(suffix) for suffix in OFFICIAL_SUFFIXES),
        "host": host,
        "score": score,
        "hit": hit,
        "recovery_mode": (
            "exact_excerpt"
            if exact_recovery
            else "value_metric"
            if value_metric_recovery
            else "value_context_candidate"
            if value_context_recovery
            else ""
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="long-history")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids-json", type=Path)
    parser.add_argument("--max-queries", type=int, default=2)
    parser.add_argument("--fetch-per-query", type=int, default=3)
    parser.add_argument("--min-interval", type=float, default=0.7)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    ids = (
        set(json.loads(args.ids_json.read_text(encoding="utf-8")))
        if args.ids_json is not None and args.ids_json.is_file()
        else set()
    )
    claims = [
        claim
        for claim in GroundTruthStore.load(GROUND_TRUTH)
        if (not args.mode or claim.research_mode == args.mode)
        and (not ids or claim.claim_id in ids)
    ][: args.limit or None]
    client = FreeWebClient(args.output / "cache", min_interval=args.min_interval)
    args.output.mkdir(parents=True, exist_ok=True)
    snapshots_dir = args.output / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output / f"retrieval_{args.mode or 'all'}.jsonl"
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as handle:
        for claim in claims:
            queries = _queries(claim)[: args.max_queries]
            fetched: dict[str, dict[str, Any]] = {}
            best: dict[str, Any] | None = None
            for query in queries:
                results = client.search(query, max_results=args.fetch_per_query + 2)
                for result in results[: args.fetch_per_query]:
                    if result.url in fetched:
                        continue
                    page = client.fetch(result.url)
                    scored = score_page(claim, page.text, page.title or result.title, result.url)
                    row = {
                        "query": query,
                        "url": result.url,
                        "title": page.title or result.title,
                        "status": page.status,
                        "content_hash": page.content_hash,
                        "retrieved_at": page.retrieved_at,
                        "error": page.error,
                        **scored,
                    }
                    fetched[result.url] = row
                    if row["hit"]:
                        snapshot_path = snapshots_dir / f"{page.content_hash}.json"
                        if not snapshot_path.is_file():
                            snapshot_path.write_text(
                                json.dumps(
                                    {
                                        "url": result.url,
                                        "title": page.title,
                                        "text": page.text,
                                        "content_hash": page.content_hash,
                                        "retrieved_at": page.retrieved_at,
                                        "query": query,
                                        "gt_claim_id": claim.claim_id,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n",
                                encoding="utf-8",
                            )
                    if best is None or row["score"] > best["score"]:
                        best = row
            hit = any(row["hit"] for row in fetched.values())
            log_row = {
                "claim_id": claim.claim_id,
                "region": claim.region,
                "mode": claim.research_mode,
                "metric": claim.metric,
                "year": claim.metric_year,
                "queries": queries,
                "recovered": hit,
                "best": best,
                "fetched": list(fetched.values()),
            }
            rows.append(log_row)
            handle.write(json.dumps(log_row, ensure_ascii=False) + "\n")
            print(
                f"[{len(rows)}/{len(claims)}] {claim.region} {claim.metric} "
                f"{claim.metric_year}: {'HIT' if hit else 'miss'} "
                f"requests={client.request_count}"
            )

    by_mode: dict[str, Counter] = defaultdict(Counter)
    by_region: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_mode[row["mode"]][("hit" if row["recovered"] else "miss")] += 1
        by_region[row["region"]][("hit" if row["recovered"] else "miss")] += 1
    recovered = [row for row in rows if row["recovered"]]
    exact_recovered = [
        row
        for row in recovered
        if row["best"] is not None and row["best"]["recovery_mode"] == "exact_excerpt"
    ]
    value_recovered = [
        row
        for row in recovered
        if row["best"] is not None and row["best"]["recovery_mode"] == "value_metric"
    ]
    context_candidates = [
        row
        for row in rows
        if not row["recovered"]
        and row["best"] is not None
        and row["best"]["recovery_mode"] == "value_context_candidate"
    ]
    official = [
        row
        for row in recovered
        if row["best"] is not None and row["best"]["official"]
    ]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "FREE_PUBLIC_WEB_RETRIEVAL",
        "provider_calls_paid": 0,
        "mode": args.mode,
        "facts": len(rows),
        "recovered": len(recovered),
        "recovered_exact_excerpt": len(exact_recovered),
        "recovered_value_metric": len(value_recovered),
        "value_context_candidates": len(context_candidates),
        "recovery_rate": round(len(recovered) / len(rows), 4) if rows else 0.0,
        "official_recovered": len(official),
        "request_count": client.request_count,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "by_mode": {mode: dict(counts) for mode, counts in sorted(by_mode.items())},
        "by_region": {region: dict(counts) for region, counts in sorted(by_region.items())},
        "missing": [
            {
                "claim_id": row["claim_id"],
                "region": row["region"],
                "metric": row["metric"],
                "year": row["year"],
                "best_score": row["best"]["score"] if row["best"] else 0,
                "best_mode": row["best"]["recovery_mode"] if row["best"] else "",
            }
            for row in rows
            if not row["recovered"]
        ],
        "notes": [
            "Public DuckDuckGo HTML search + direct page fetch; no paid API.",
            "Queries are derived from region/metric/year, not the GT URL.",
            "Recovery is excerpt exact or value+metric+region; not a quality claim.",
        ],
    }
    (args.output / f"summary_{args.mode or 'all'}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
