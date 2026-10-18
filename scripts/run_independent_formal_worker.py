"""正式 E1 批次的单组独立进程入口。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_independent_formal import (
    FORMAL_GATE_PATH,
    FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    FORMAL_GROUND_TRUTH_PATH,
)
from scripts.run_independent_smoke import (
    _run_baseline,
    _run_county_research_ai,
    _smoke_settings,
)

from county_research_ai.evaluation.experiment_agents import (
    GeneralPurposeAIResearcher,
    TraditionalSearchResearcher,
)
from county_research_ai.evaluation.experiment_models import RunArtifact
from county_research_ai.evaluation.experiment_runner import (
    ExperimentRunner,
    ExperimentRunSpec,
)
from county_research_ai.evaluation.gate import (
    require_formal_api_gate,
    require_frozen_ground_truth,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager

FORMAL_LLM_CAPACITY = 100_000
FORMAL_SEARCH_CAPACITY = 500


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--group", choices=["A", "B", "C"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--search-provider", required=True)
    parser.add_argument("--county", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--focus", required=True)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--max-search-results", type=int, default=1)
    parser.add_argument("--llm-tasks", default="industry_status")
    args = parser.parse_args()

    require_formal_api_gate(FORMAL_GATE_PATH)
    require_frozen_ground_truth(
        FORMAL_GROUND_TRUTH_PATH,
        FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    )
    tasks = [item for item in args.llm_tasks.split(",") if item]
    settings = _smoke_settings(
        max_tokens=args.max_tokens,
        max_results=args.max_search_results,
        tasks=tasks,
    )
    settings.llm.model = args.model
    settings.search.provider = args.search_provider
    manager = ResourceManager(
        args.resource_db,
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
    spec = ExperimentRunSpec(
        run_id=args.run_id,
        experiment_id="E1",
        group=args.group,
        county=args.county,
        task_id=args.task_id,
        mode=args.task_id,
        model=args.model,
        search_provider=args.search_provider,
        config={
            "formal_target": True,
            "model": args.model,
            "search_provider": args.search_provider,
            "group": args.group,
            "county": args.county,
            "focus": args.focus,
            "task_id": args.task_id,
            "max_llm_tokens": args.max_tokens,
            "max_search_results": args.max_search_results,
            "llm_tasks": tasks,
            "search_enabled": True,
        },
    )
    runner = ExperimentRunner(args.root, manager)
    if args.group == "A":
        def execute(artifact: RunArtifact):
            return _run_baseline(
                spec,
                artifact,
                manager,
                TraditionalSearchResearcher(),
                max_tokens=args.max_tokens,
                max_results=args.max_search_results,
            )
    elif args.group == "B":
        def execute(artifact: RunArtifact):
            return _run_baseline(
                spec,
                artifact,
                manager,
                GeneralPurposeAIResearcher(),
                max_tokens=args.max_tokens,
                max_results=args.max_search_results,
            )
    else:
        def execute(artifact: RunArtifact):
            return _run_county_research_ai(
                spec,
                artifact,
                manager,
                max_tokens=args.max_tokens,
                max_results=args.max_search_results,
                tasks=tasks,
            )
    manifest = runner.run(spec, execute)
    print(json.dumps({"run_id": manifest.run_id, "status": manifest.status.value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
