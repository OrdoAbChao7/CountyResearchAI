"""Oracle source probe: fetch the GT URL directly to measure source availability.

This is NOT autonomous retrieval and must not be reported as Strategy D. It
answers a narrower question: if a source URL were known, is the fact still
present and fetchable? Free public fetch only; no paid API.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scripts.diagnose_quality_funnel import GROUND_TRUTH
from scripts.q7_retrieve_missing import score_page

from county_research_ai.evaluation.ground_truth import GroundTruthStore
from county_research_ai.search.public_web import FreeWebClient

OUTPUT = Path("experiments/quality/20261026_q7_oracle_probe")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--mode", default="")
    parser.add_argument("--min-interval", type=float, default=0.3)
    parser.add_argument(
        "--missing-json",
        type=Path,
        default=Path("experiments/quality/20261026_q7_corpus/missing_facts.json"),
    )
    args = parser.parse_args()
    missing_ids = {
        row["claim_id"]
        for row in json.loads(args.missing_json.read_text(encoding="utf-8"))
    }
    claims = [
        claim
        for claim in GroundTruthStore.load(GROUND_TRUTH)
        if claim.claim_id in missing_ids
        and (not args.mode or claim.research_mode == args.mode)
    ]
    client = FreeWebClient(args.output / "cache", min_interval=args.min_interval)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    started = time.monotonic()
    for claim in claims:
        page = client.fetch(claim.url)
        scored = score_page(claim, page.text, page.title, claim.url)
        rows.append(
            {
                "claim_id": claim.claim_id,
                "region": claim.region,
                "mode": claim.research_mode,
                "metric": claim.metric,
                "year": claim.metric_year,
                "url": claim.url,
                "status": page.status,
                "error": page.error,
                "content_hash": page.content_hash,
                "text_length": len(page.text),
                **scored,
            }
        )
        print(
            f"[{len(rows)}/{len(claims)}] {claim.region} {claim.metric}: "
            f"{scored['recovery_mode'] or 'miss'} status={page.status}"
        )
    by_mode: dict[str, Counter] = {}
    for row in rows:
        by_mode.setdefault(row["mode"], Counter())[
            row["recovery_mode"] or "miss"
        ] += 1
    recovered = [row for row in rows if row["hit"]]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "ORACLE_GT_URL_FETCH",
        "provider_calls_paid": 0,
        "note": (
            "GT URL is used as an oracle; this measures source availability, "
            "not autonomous retrieval and not Strategy D."
        ),
        "facts": len(rows),
        "recovered": len(recovered),
        "recovery_rate": round(len(recovered) / len(rows), 4) if rows else 0.0,
        "recovery_modes": dict(sorted(Counter(row["recovery_mode"] or "miss" for row in rows).items())),
        "by_mode": {mode: dict(counter) for mode, counter in sorted(by_mode.items())},
        "unreachable": [
            row for row in rows if row["status"] == 0 or row["status"] >= 400
        ],
        "request_count": client.request_count,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "rows.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
