"""Validate the Q2 blind pilot and write its reproducibility manifest.

Checks each blind fact against the archived snapshot: file hash, document URL,
exact quote presence, quote hash, value/unit presence, and period evidence. The
blind tasks must be disjoint from the inherited dev-replay task keys.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from county_research_ai.evaluation.ground_truth import GroundTruthStore
from county_research_ai.evidence.graph import _quote_contains_value

ROOT = Path(__file__).resolve().parents[1]
BLIND = ROOT / "experiments/quality/dataset/blind_pilot.jsonl"
GROUND_TRUTH = (
    ROOT
    / "experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl"
)
OUTPUT = ROOT / "experiments/quality/dataset"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_blind() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in BLIND.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_fact(fact: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    snapshot_path = ROOT / fact["snapshot_path"]
    if not snapshot_path.is_file():
        return {"fact_id": fact["fact_id"], "ok": False, "errors": ["snapshot_missing"]}
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot_hash = sha256_bytes(snapshot_bytes)
    try:
        documents = json.loads(snapshot_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"fact_id": fact["fact_id"], "ok": False, "errors": ["snapshot_invalid"]}
    index = int(fact["snapshot_doc_index"])
    if not (0 <= index < len(documents)):
        return {"fact_id": fact["fact_id"], "ok": False, "errors": ["doc_index_out_of_range"]}
    document = documents[index]
    if document.get("url") != fact["url"]:
        errors.append("url_mismatch")
    content = document.get("content") or document.get("snippet") or ""
    quote = fact["quote"]
    if quote not in content:
        errors.append("quote_not_in_snapshot")
    quote_hash = sha256_bytes(quote.encode("utf-8"))
    if not _quote_contains_value(quote, str(fact["value"]), str(fact["unit"])):
        errors.append("value_unit_not_in_quote")
    if str(fact["value"]) not in fact["expected_answer"]:
        errors.append("expected_answer_missing_value")
    period = str(fact["period"])
    period_evidence = " ".join(
        [
            quote,
            str(document.get("title", "")),
            str(document.get("url", "")),
            str(document.get("published_at", "")),
        ]
    )
    if period not in period_evidence:
        errors.append("period_not_evidenced")
    return {
        "task_id": fact["task_id"],
        "fact_id": fact["fact_id"],
        "ok": not errors,
        "errors": errors,
        "snapshot_sha256": snapshot_hash,
        "quote_sha256": quote_hash,
    }


def build_manifest(blind: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    dev_claims = GroundTruthStore.load(GROUND_TRUTH)
    dev_tasks = sorted({(claim.region, claim.research_mode) for claim in dev_claims})
    blind_tasks = sorted({(fact["region"], fact["mode"]) for fact in blind})
    overlap = set(dev_tasks) & set(blind_tasks)
    task_hashes = {}
    for fact in blind:
        task_hashes.setdefault(
            fact["task_id"],
            {
                "snapshot_sha256": sha256_bytes((ROOT / fact["snapshot_path"]).read_bytes()),
                "snapshot_path": fact["snapshot_path"],
                "url": fact["url"],
                "source_title": fact["source_title"],
            },
        )
    counts = Counter(fact["task_id"] for fact in blind)
    return {
        "status": "VALIDATED_BLIND_PILOT" if all(item["ok"] for item in results) and not overlap else "INVALID",
        "blind_file": str(BLIND.relative_to(ROOT)),
        "blind_file_sha256": sha256_bytes(BLIND.read_bytes()),
        "blind_tasks": dict(sorted(counts.items())),
        "blind_facts": len(blind),
        "blind_regions_tasks": [list(item) for item in blind_tasks],
        "dev_replay": {
            "ground_truth": str(GROUND_TRUTH.relative_to(ROOT)),
            "ground_truth_sha256": sha256_bytes(GROUND_TRUTH.read_bytes()),
            "tasks": len(dev_tasks),
            "task_keys": [list(item) for item in dev_tasks],
            "facts": len(dev_claims),
            "split": "dev_replay",
            "independent": False,
            "note": "Inherited frozen corpus used for Q1 diagnosis and Q3 tuning; not a blind set.",
        },
        "blind_pilot": {
            "split": "blind_pilot",
            "tasks": len(counts),
            "facts": len(blind),
            "task_hashes": task_hashes,
            "independent_of_dev": not overlap,
        },
        "coverage_gap": {
            "target_min_tasks": 40,
            "target_max_tasks": 60,
            "achieved_blind_tasks": len(counts),
            "missing_blind_tasks_min": max(0, 40 - len(counts)),
            "missing_blind_tasks_max": max(0, 60 - len(counts)),
            "reason": (
                "Only two disjoint archived sources had verifiable exact quotes and "
                "hashes without new retrieval or human annotation. The 18 inherited "
                "tasks are not independent. No paid search/annotation was authorized."
            ),
        },
        "leakage_controls": {
            "dev_blind_task_overlap": [list(item) for item in sorted(overlap)],
            "blind_used_in_q1": False,
            "tuning_uses_blind": False,
        },
        "validation": {
            "ok": all(item["ok"] for item in results),
            "failures": [item for item in results if not item["ok"]],
            "facts": results,
        },
    }


def main() -> int:
    blind = load_blind()
    results = [validate_fact(fact) for fact in blind]
    manifest = build_manifest(blind, results)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "validation.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": manifest["status"],
        "blind_tasks": manifest["blind_tasks"],
        "blind_facts": manifest["blind_facts"],
        "failures": len(manifest["validation"]["failures"]),
    }, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "VALIDATED_BLIND_PILOT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
