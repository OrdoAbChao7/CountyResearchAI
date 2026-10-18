from __future__ import annotations

import json

import pytest
import yaml
from scripts.build_benchmark_ground_truth import build_benchmark_ground_truth


def _claim(claim_id: str, mode: str, region: str = "示例县") -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "claim": f"{mode} claim {claim_id}",
        "source": "official bulletin",
        "url": f"https://example.gov.cn/{claim_id}",
        "date": "2024-01-01",
        "region": region,
        "metric": "industry output",
        "unit": "亿元",
        "evidence_excerpt": "official evidence",
        "confidence": "high",
        "verification_status": "VERIFIED",
        "verification_sources": ["official-a", "official-b"],
        "verification_contexts": ["context-a", "context-b"],
        "research_mode": mode,
        "expected_answer": "industry output is 10 billion yuan",
        "source_title": "official bulletin",
        "source_date": "2025-03-01",
        "metric_year": "2024",
        "administrative_scope": "county-level",
    }


def test_builder_freezes_task_matched_claims_and_writes_hash_manifest(tmp_path):
    source = tmp_path / "claims.jsonl"
    rows = [
        _claim("claim-snapshot", "snapshot"),
        _claim("claim-rise-fall", "rise-fall"),
        _claim("claim-history", "long-history"),
    ]
    source.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    regions = tmp_path / "regions.yaml"
    regions.write_text(
        yaml.safe_dump(
            {
                "status": "DRAFT_HOLDOUT_REGIONS",
                "claim_quota": {"min": 3, "max": 3},
                "tasks": {"snapshot": 1, "rise-fall": 1, "long-history": 1},
                "regions": [{"id": "region-1", "name": "示例县"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "ground_truth.jsonl"
    manifest = tmp_path / "manifest.json"

    result = build_benchmark_ground_truth(
        source_path=source,
        regions_path=regions,
        output_path=output,
        manifest_path=manifest,
    )

    assert result["status"] == "FROZEN_CONTINUATION_BENCHMARK"
    assert result["claim_count"] == 3
    written_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert written_manifest["source_hash"] == result["source_hash"]
    assert len(output.read_text(encoding="utf-8").splitlines()) == 3


def test_builder_rejects_quota_or_cross_verification_drift(tmp_path):
    source = tmp_path / "claims.jsonl"
    row = _claim("claim-snapshot", "snapshot")
    row["verification_contexts"] = ["only-one"]
    source.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    regions = tmp_path / "regions.yaml"
    regions.write_text(
        yaml.safe_dump(
            {
                "status": "DRAFT_HOLDOUT_REGIONS",
                "claim_quota": {"min": 3, "max": 3},
                "tasks": {"snapshot": 3},
                "regions": [{"id": "region-1", "name": "示例县"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="two verification contexts"):
        build_benchmark_ground_truth(
            source_path=source,
            regions_path=regions,
            output_path=tmp_path / "ground_truth.jsonl",
            manifest_path=tmp_path / "manifest.json",
        )
