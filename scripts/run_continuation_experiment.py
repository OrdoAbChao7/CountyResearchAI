"""Run the frozen continuation benchmark with the authorized provider mix."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.run_independent_smoke import _run_baseline, _run_county_research_ai

from county_research_ai.config import load_settings
from county_research_ai.evaluation.experiment_agents import (
    GeneralPurposeAIResearcher,
    TraditionalSearchResearcher,
)
from county_research_ai.evaluation.experiment_models import RunArtifact, RunStatus
from county_research_ai.evaluation.experiment_runner import ExperimentRunner, ExperimentRunSpec
from county_research_ai.evaluation.gate import require_formal_api_gate
from county_research_ai.evaluation.ground_truth import GroundTruthStore
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
CONTINUATION_ROOT = FORMAL_ROOT
GATE_PATH = FORMAL_ROOT / "manifests" / "continuation_resource_gate_20261018.json"
GROUND_TRUTH_PATH = FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019.jsonl"
GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "continuation_ground_truth_20261019_manifest.json"
)
REGIONS_PATH = FORMAL_ROOT / "datasets" / "independent_regions_20261018.yaml"
RESOURCE_DB_DEFAULT = FORMAL_ROOT / "runs" / "continuation_resource_manager_20261019.sqlite"
LLM_CAPACITY = 180_000
SEARCH_CAPACITY = 220
MATCHED_LLM_BUDGET = 90_000
MATCHED_SEARCH_BUDGET = 6
MATCHED_WALL_CLOCK_SECONDS = 120
MODES = ("snapshot", "rise-fall", "long-history")


def load_continuation_regions(path: Path = REGIONS_PATH) -> list[dict[str, Any]]:
    import yaml

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "FROZEN_CONTINUATION_BENCHMARK":
        raise ValueError("continuation regions must be FROZEN_CONTINUATION_BENCHMARK")
    regions = payload.get("regions")
    if not isinstance(regions, list) or len(regions) != 6:
        raise ValueError("continuation benchmark must contain exactly six regions")
    return [dict(region) for region in regions]


def validate_continuation_benchmark() -> dict[str, Any]:
    bundle = GroundTruthStore.freeze_continuation_verified(
        GROUND_TRUTH_PATH,
        GROUND_TRUTH_MANIFEST_PATH,
    )
    regions = load_continuation_regions()
    region_names = {str(region["name"]) for region in regions}
    modes = {mode: 0 for mode in MODES}
    per_region_mode: dict[tuple[str, str], int] = {}
    for claim in bundle.claims:
        if claim.region not in region_names:
            raise ValueError(f"claim region is outside frozen region list: {claim.region}")
        if claim.research_mode not in modes:
            raise ValueError(f"claim mode is outside frozen mode list: {claim.research_mode}")
        modes[claim.research_mode] += 1
        key = (claim.region, claim.research_mode)
        per_region_mode[key] = per_region_mode.get(key, 0) + 1
    expected_keys = {(region, mode) for region in region_names for mode in MODES}
    if set(per_region_mode) != expected_keys or set(per_region_mode.values()) != {5}:
        raise ValueError(f"continuation task quotas are not 6x3x5: {per_region_mode}")
    if modes != {mode: 30 for mode in MODES}:
        raise ValueError(f"continuation mode quotas are not 30 each: {modes}")
    return {
        "claim_count": len(bundle.claims),
        "source_hash": bundle.source_hash,
        "regions": len(region_names),
        "modes": modes,
        "claims_per_region_mode": 5,
    }


def _focus(region: str, mode: str) -> str:
    return {
        "snapshot": f"{region}产业现状与2024年主要经济指标",
        "rise-fall": f"{region}产业发展变化、升降与转折机制",
        "long-history": f"{region}产业结构演变与工业历史",
    }[mode]


def build_continuation_specs(
    *,
    model: str,
    search_provider: str,
    batch_id: str,
    region_names: list[str] | None = None,
    modes: list[str] | None = None,
    repeats: int = 1,
    execution_policy: str = "natural",
) -> list[ExperimentRunSpec]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if execution_policy not in {"natural", "matched_budget"}:
        raise ValueError("execution_policy must be natural or matched_budget")
    regions = load_continuation_regions()
    by_name = {str(region["name"]): region for region in regions}
    selected_regions = region_names or list(by_name)
    unknown = sorted(set(selected_regions) - set(by_name))
    if unknown:
        raise ValueError(f"unknown continuation regions: {', '.join(unknown)}")
    selected_modes = modes or list(MODES)
    unknown_modes = sorted(set(selected_modes) - set(MODES))
    if unknown_modes:
        raise ValueError(f"unknown continuation modes: {', '.join(unknown_modes)}")
    specs: list[ExperimentRunSpec] = []
    for repeat in range(1, repeats + 1):
        for region_name in selected_regions:
            region_id = str(by_name[region_name]["id"])
            for mode in selected_modes:
                for group in ("A", "B", "C"):
                    run_id = f"{batch_id}_{region_id}_{mode}_r{repeat}_{group}"
                    specs.append(
                        ExperimentRunSpec(
                            run_id=run_id,
                            experiment_id="continuation-natural-execution"
                            if execution_policy == "natural"
                            else "continuation-matched-budget",
                            group=group,
                            county=region_name,
                            task_id=mode,
                            mode=mode,
                            model=model,
                            search_provider=search_provider,
                            config={
                                "batch_id": batch_id,
                                "formal_target": True,
                                "continuation_benchmark": True,
                                "execution_policy": execution_policy,
                                "model": model,
                                "search_provider": search_provider,
                                "group": group,
                                "county": region_name,
                                "region_id": region_id,
                                "focus": _focus(region_name, mode),
                                "task_id": mode,
                                "mode": mode,
                                "repeat": repeat,
                                "max_llm_tokens": 2048,
                                "max_search_results": 2,
                                "llm_tasks": ["industry_status"],
                                "search_enabled": True,
                                "ground_truth_manifest": str(GROUND_TRUTH_MANIFEST_PATH),
                                "ground_truth_claim_quota": 5,
                                "matched_budget": (
                                    {
                                        "llm_units": MATCHED_LLM_BUDGET,
                                        "search_requests": MATCHED_SEARCH_BUDGET,
                                        "wall_clock_seconds": MATCHED_WALL_CLOCK_SECONDS,
                                    }
                                    if execution_policy == "matched_budget"
                                    else None
                                ),
                            },
                        )
                    )
    return specs


def _write_batch_manifest(
    root: Path,
    *,
    batch_id: str,
    specs: list[ExperimentRunSpec],
    benchmark: dict[str, Any],
    resource_db: Path,
) -> None:
    payload = {
        "batch_id": batch_id,
        "status": "RUNNING",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_policy": specs[0].config["execution_policy"] if specs else None,
        "benchmark": benchmark,
        "ground_truth_path": str(GROUND_TRUTH_PATH),
        "ground_truth_manifest_path": str(GROUND_TRUTH_MANIFEST_PATH),
        "resource_db": str(resource_db),
        "planned_runs": [spec.run_id for spec in specs],
        "config": [spec.config for spec in specs],
    }
    (root / "batch_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_batch(
    *,
    region_names: list[str],
    batch_id: str,
    resource_db: Path = RESOURCE_DB_DEFAULT,
    modes: list[str] | None = None,
    execution_policy: str = "natural",
    repeats: int = 1,
    llm_capacity: int = LLM_CAPACITY,
    search_capacity: int = SEARCH_CAPACITY,
) -> dict[str, Any]:
    gate_result = require_formal_api_gate(GATE_PATH)
    benchmark = validate_continuation_benchmark()
    settings = load_settings()
    gate = gate_result["gate"]
    if settings.llm.provider.lower() != str(gate["llm_provider"]).lower():
        raise ValueError(".env LLM provider does not match continuation gate")
    if settings.search.provider.lower() != str(gate["search_provider"]).lower():
        raise ValueError(".env search provider does not match continuation gate")
    if settings.llm.model != str(gate["model"]):
        raise ValueError(".env LLM model does not match continuation gate")
    specs = build_continuation_specs(
        model=settings.llm.model,
        search_provider=settings.search.provider,
        batch_id=batch_id,
        region_names=region_names,
        modes=modes,
        repeats=repeats,
        execution_policy=execution_policy,
    )
    root = CONTINUATION_ROOT / "runs" / batch_id
    if root.exists():
        raise FileExistsError(f"continuation batch directory already exists: {root}")
    root.mkdir(parents=True)
    run_limits = None
    if execution_policy == "matched_budget":
        llm_key = (settings.llm.provider, settings.llm.model, "llm")
        search_key = (settings.search.provider, "search", "search")
        run_limits = {
            spec.run_id: {
                llm_key: MATCHED_LLM_BUDGET,
                search_key: MATCHED_SEARCH_BUDGET,
            }
            for spec in specs
        }
    manager = ResourceManager(
        Path(resource_db),
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(
                llm_capacity,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider.lower() == "deepseek"
                    else "free_confirmed"
                ),
            ),
            (settings.search.provider, "search", "search"): ResourceLimit(
                search_capacity, billing_class="free_confirmed"
            ),
        },
        run_limits=run_limits,
    )
    runner = ExperimentRunner(
        root,
        manager,
        max_duration_seconds=(
            MATCHED_WALL_CLOCK_SECONDS if execution_policy == "matched_budget" else None
        ),
    )
    _write_batch_manifest(
        root,
        batch_id=batch_id,
        specs=specs,
        benchmark=benchmark,
        resource_db=Path(resource_db),
    )
    results: dict[str, str] = {}
    stopped_reason: str | None = None
    for spec in specs:
        if spec.group == "A":
            def execute(artifact: RunArtifact, current: ExperimentRunSpec = spec):
                return _run_baseline(
                    current,
                    artifact,
                    manager,
                    TraditionalSearchResearcher(),
                    max_tokens=2048,
                    max_results=2,
                )
        elif spec.group == "B":
            def execute(artifact: RunArtifact, current: ExperimentRunSpec = spec):
                return _run_baseline(
                    current,
                    artifact,
                    manager,
                    GeneralPurposeAIResearcher(),
                    max_tokens=2048,
                    max_results=2,
                )
        else:
            def execute(artifact: RunArtifact, current: ExperimentRunSpec = spec):
                return _run_county_research_ai(
                    current,
                    artifact,
                    manager,
                    max_tokens=2048,
                    max_results=2,
                    tasks=["industry_status"],
                )
        manifest = runner.run(spec, execute)
        results[spec.run_id] = manifest.status.value
        print(json.dumps({"run_id": spec.run_id, "status": manifest.status.value}, ensure_ascii=False))
        if (
            manifest.status is not RunStatus.VALID
            and not (
                execution_policy == "matched_budget"
                and manifest.status is RunStatus.BUDGET_EXHAUSTED
            )
        ):
            stopped_reason = f"provider_or_resource_stop:{manifest.status.value}"
            break
    completed = len(results)
    skipped = [spec.run_id for spec in specs if spec.run_id not in results]
    status = (
        "VALID"
        if completed == len(specs) and all(status == RunStatus.VALID.value for status in results.values())
        else "BUDGET_EXHAUSTED"
        if completed == len(specs)
        and any(status == RunStatus.BUDGET_EXHAUSTED.value for status in results.values())
        else "STOPPED"
    )
    summary = {
        "status": status,
        "batch_id": batch_id,
        "execution_policy": execution_policy,
        "planned_runs": len(specs),
        "completed_runs": completed,
        "skipped_runs": skipped,
        "stopped_reason": stopped_reason,
        "results": results,
        "benchmark": benchmark,
        "resource_snapshot": {
            "consumed": {"|".join(key): value for key, value in manager.snapshot().consumed.items()},
            "reserved": {"|".join(key): value for key, value in manager.snapshot().reserved.items()},
            "active": manager.snapshot().active,
        },
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    batch_manifest = json.loads((root / "batch_manifest.json").read_text(encoding="utf-8"))
    batch_manifest.update({"status": status, "summary": "summary.json"})
    (root / "batch_manifest.json").write_text(
        json.dumps(batch_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", action="append", dest="regions", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--resource-db", type=Path, default=RESOURCE_DB_DEFAULT)
    parser.add_argument("--mode", action="append", dest="modes")
    parser.add_argument("--execution-policy", choices=("natural", "matched_budget"), default="natural")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--llm-capacity", type=int, default=LLM_CAPACITY)
    parser.add_argument("--search-capacity", type=int, default=SEARCH_CAPACITY)
    args = parser.parse_args()
    print(
        json.dumps(
            run_batch(
                region_names=args.regions,
                batch_id=args.batch_id,
                resource_db=args.resource_db,
                modes=args.modes,
                execution_policy=args.execution_policy,
                repeats=args.repeats,
                llm_capacity=args.llm_capacity,
                search_capacity=args.search_capacity,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
