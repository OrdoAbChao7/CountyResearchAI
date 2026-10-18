"""从预先审计的来源 Claim JSONL 冻结 continuation Benchmark。

该脚本只做本地校验和写入，不抓取网页、不调用搜索或 LLM Provider。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore


def build_benchmark_ground_truth(
    *,
    source_path: Path,
    regions_path: Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    config = _load_region_config(regions_path)
    claims = _load_claims(source_path)
    GroundTruthStore.validate_rich_claims(claims)
    _validate_region_and_task_quotas(claims, config)

    GroundTruthStore.write(output_path, claims)
    source_hash = hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
    manifest = {
        "status": "FROZEN_CONTINUATION_BENCHMARK",
        "schema_version": "continuation-v1",
        "freeze_scope": "independent_task_matched_claims",
        "source_path": str(Path(source_path)),
        "source_hash": source_hash,
        "claim_count": len(claims),
        "regions": sorted({claim.region for claim in claims}),
        "claims_per_region": dict(sorted(Counter(claim.region for claim in claims).items())),
    }
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(manifest_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_claims(path: Path) -> list[GroundTruthClaim]:
    claims: list[GroundTruthClaim] = []
    seen: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            claim = GroundTruthClaim.from_dict(json.loads(line))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid benchmark claim at line {line_number}") from exc
        if claim.claim_id in seen:
            raise ValueError(f"duplicate benchmark claim_id: {claim.claim_id}")
        seen.add(claim.claim_id)
        claims.append(claim)
    if not claims:
        raise ValueError("benchmark source must contain at least one claim")
    return claims


def _load_region_config(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("benchmark regions config must be an object")
    regions = value.get("regions")
    quota = value.get("claim_quota")
    tasks = value.get("tasks")
    if not isinstance(regions, list) or not regions:
        raise ValueError("benchmark regions config must define regions")
    if not isinstance(quota, dict) or not isinstance(tasks, dict) or not tasks:
        raise ValueError("benchmark regions config must define claim_quota and tasks")
    minimum = quota.get("min")
    maximum = quota.get("max")
    if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum <= 0:
        raise ValueError("benchmark claim_quota min/max must be positive integers")
    if maximum < minimum:
        raise ValueError("benchmark claim_quota max must be >= min")
    names = [str(region.get("name", "")) for region in regions if isinstance(region, dict)]
    if len(names) != len(set(names)) or any(not name for name in names):
        raise ValueError("benchmark region names must be unique and non-empty")
    return {"region_names": set(names), "minimum": minimum, "maximum": maximum, "tasks": tasks}


def _validate_region_and_task_quotas(
    claims: list[GroundTruthClaim], config: dict[str, Any]
) -> None:
    known_regions = config["region_names"]
    unknown = sorted({claim.region for claim in claims} - known_regions)
    if unknown:
        raise ValueError(f"claims contain unknown regions: {', '.join(unknown)}")
    by_region = Counter(claim.region for claim in claims)
    by_region_task = Counter((claim.region, claim.research_mode) for claim in claims)
    for region in sorted(known_regions):
        count = by_region[region]
        if not config["minimum"] <= count <= config["maximum"]:
            raise ValueError(
                f"claim quota out of range for {region}: {count} "
                f"(expected {config['minimum']}..{config['maximum']})"
            )
        for task, expected in config["tasks"].items():
            actual = by_region_task[(region, str(task))]
            if actual != int(expected):
                raise ValueError(
                    f"task quota mismatch for {region}/{task}: {actual} != {expected}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_benchmark_ground_truth(
                source_path=args.source,
                regions_path=args.regions,
                output_path=args.output,
                manifest_path=args.manifest,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
