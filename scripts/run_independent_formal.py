"""编排冻结六地区的正式 E1 端到端 A/B/C 批次。

入口在任何运行目录或业务 API 调用前检查持久化 formal gate；当前 gate 未打开时
应明确拒绝，而不是生成伪正式结果。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from county_research_ai.config import load_settings
from county_research_ai.evaluation.checkpoints import CheckpointStore
from county_research_ai.evaluation.experiment_models import RunStatus
from county_research_ai.evaluation.experiment_runner import ExperimentRunSpec
from county_research_ai.evaluation.gate import (
    require_formal_api_gate,
    require_frozen_ground_truth,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
FORMAL_REGIONS_PATH = FORMAL_ROOT / "datasets" / "formal_regions_20261018.yaml"
FORMAL_GATE_PATH = FORMAL_ROOT / "manifests" / "formal_target_gate_20261018.json"
FORMAL_GROUND_TRUTH_PATH = FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018.jsonl"
FORMAL_GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018_manifest.json"
)
FORMAL_LLM_CAPACITY = 100_000
FORMAL_SEARCH_CAPACITY = 500


def load_formal_regions(path: Path = FORMAL_REGIONS_PATH) -> list[dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("status") != "FROZEN":
        raise ValueError("formal regions must be FROZEN")
    regions = payload.get("regions")
    if not isinstance(regions, list) or len(regions) < 6:
        raise ValueError("formal regions must contain at least six regions")
    return [dict(region) for region in regions]


def build_formal_specs(
    *,
    model: str,
    search_provider: str,
    batch_id: str,
    region_names: list[str] | None = None,
    repeats: int = 1,
    max_tokens: int = 2048,
    max_search_results: int = 1,
    llm_tasks: list[str] | None = None,
) -> list[ExperimentRunSpec]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    regions = load_formal_regions()
    by_name = {str(region["name"]): region for region in regions}
    selected_names = region_names or list(by_name)
    unknown = sorted(set(selected_names) - set(by_name))
    if unknown:
        raise ValueError(f"unknown formal regions: {', '.join(unknown)}")
    tasks = list(llm_tasks or ["industry_status"])
    specs: list[ExperimentRunSpec] = []
    for repeat in range(1, repeats + 1):
        for name in selected_names:
            region = by_name[name]
            task_id = str(region.get("primary_task") or region.get("task_ids", ["snapshot"])[0])
            focus = str(region.get("focus", "县域产业发展"))
            for group in ("A", "B", "C"):
                run_id = f"{batch_id}_{region['id']}_{name}_{task_id}_r{repeat}_{group}"
                specs.append(
                    ExperimentRunSpec(
                        run_id=run_id,
                        experiment_id="E1",
                        group=group,
                        county=name,
                        task_id=task_id,
                        mode=task_id,
                        model=model,
                        search_provider=search_provider,
                        config={
                            "batch_id": batch_id,
                            "formal_target": True,
                            "model": model,
                            "search_provider": search_provider,
                            "group": group,
                            "county": name,
                            "focus": focus,
                            "task_id": task_id,
                            "repeat": repeat,
                            "max_llm_tokens": max_tokens,
                            "max_search_results": max_search_results,
                            "llm_tasks": tasks,
                            "search_enabled": True,
                        },
                    )
                )
    return specs


def formal_worker_command(
    spec: ExperimentRunSpec,
    *,
    root: Path,
    resource_db: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.run_independent_formal_worker",
        "--root",
        str(Path(root).resolve()),
        "--resource-db",
        str(Path(resource_db).resolve()),
        "--run-id",
        spec.run_id,
        "--group",
        spec.group,
        "--model",
        spec.model,
        "--search-provider",
        spec.search_provider,
        "--county",
        spec.county,
        "--task-id",
        spec.task_id,
        "--focus",
        str(spec.config["focus"]),
        "--max-tokens",
        str(spec.config["max_llm_tokens"]),
        "--max-search-results",
        str(spec.config["max_search_results"]),
        "--llm-tasks",
        ",".join(spec.config["llm_tasks"]),
    ]


def run_batch(
    *,
    region_names: list[str],
    repeats: int = 1,
    max_tokens: int = 2048,
    max_search_results: int = 1,
    llm_tasks: list[str] | None = None,
    batch_id: str | None = None,
    resume: bool = False,
) -> dict[str, str]:
    require_formal_api_gate(FORMAL_GATE_PATH)
    require_frozen_ground_truth(
        FORMAL_GROUND_TRUTH_PATH,
        FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    )
    settings = load_settings()
    batch_id = batch_id or datetime.now(timezone.utc).strftime("formal_%Y%m%dT%H%M%SZ")
    frozen_tasks = list(llm_tasks or ["industry_status"])
    selected_regions = list(region_names or [
        str(region["name"]) for region in load_formal_regions()
    ])
    specs = build_formal_specs(
        model=settings.llm.model,
        search_provider=settings.search.provider,
        batch_id=batch_id,
        region_names=selected_regions,
        repeats=repeats,
        max_tokens=max_tokens,
        max_search_results=max_search_results,
        llm_tasks=frozen_tasks,
    )
    root = FORMAL_ROOT / "runs" / batch_id
    if root.exists() and not resume:
        raise FileExistsError(f"formal batch directory already exists: {root}")
    checkpoint_config = {
        "batch_id": batch_id,
        "experiment_id": "E1",
        "model": settings.llm.model,
        "search_provider": settings.search.provider,
        "regions": selected_regions,
        "repeats": repeats,
        "max_tokens": max_tokens,
        "max_search_results": max_search_results,
        "llm_tasks": frozen_tasks,
    }
    checkpoint = CheckpointStore(root / "checkpoint.json")
    checkpoint_state = checkpoint.start(config=checkpoint_config, resume=resume)
    resource_db = root / "resources.sqlite"
    ResourceManager(
        resource_db,
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(
                FORMAL_LLM_CAPACITY,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider == "deepseek"
                    else "free_confirmed"
                ),
            ),
            (settings.search.provider, "search", "search"): ResourceLimit(
                FORMAL_SEARCH_CAPACITY,
                billing_class=(
                    "paid_authorized"
                    if settings.search.provider == "deepseek"
                    else "free_confirmed"
                ),
            ),
        },
    )
    results: dict[str, str] = dict(checkpoint_state.get("completed", {}))
    for spec in specs:
        manifest_path = root / spec.run_id / "manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = str(payload.get("status", ""))
            if status in {item.value for item in RunStatus if item not in {
                RunStatus.PLANNED,
                RunStatus.RUNNING,
            }}:
                results[spec.run_id] = status
                checkpoint.record(config=checkpoint_config, run_id=spec.run_id, status=status)
                continue
            raise RuntimeError(
                f"cannot resume non-terminal formal run: {spec.run_id} ({status or 'missing status'})"
            )
        if spec.run_id in results:
            raise RuntimeError(f"checkpoint references missing run manifest: {spec.run_id}")
        subprocess.run(
            formal_worker_command(spec, root=root, resource_db=resource_db),
            cwd=FORMAL_ROOT.parent.parent,
            check=True,
        )
        manifest_path = root / spec.run_id / "manifest.json"
        results[spec.run_id] = json.loads(manifest_path.read_text(encoding="utf-8"))["status"]
        checkpoint.record(
            config=checkpoint_config,
            run_id=spec.run_id,
            status=results[spec.run_id],
        )
    (root / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", action="append", dest="regions")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--max-search-results", type=int, default=1)
    parser.add_argument("--llm-tasks", default="industry_status")
    parser.add_argument("--batch-id")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.regions:
        parser.error("at least one --region is required; use one flag per region")
    results = run_batch(
        region_names=args.regions,
        repeats=args.repeats,
        max_tokens=args.max_tokens,
        max_search_results=args.max_search_results,
        llm_tasks=[item for item in args.llm_tasks.split(",") if item],
        batch_id=args.batch_id,
        resume=args.resume,
    )
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
