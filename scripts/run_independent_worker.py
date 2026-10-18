"""执行单个独立实验组；由编排脚本以独立 Python 进程调用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_independent_smoke import (
    _run_baseline,
    _run_county_research_ai,
    _smoke_settings,
    build_pilot_specs,
)

from county_research_ai.evaluation.experiment_agents import (
    GeneralPurposeAIResearcher,
    TraditionalSearchResearcher,
)
from county_research_ai.evaluation.experiment_runner import ExperimentRunner
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--group", choices=["A", "B", "C"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--search-provider", required=True)
    args = parser.parse_args()

    settings = _smoke_settings(max_tokens=512, max_results=1, tasks=["industry_status"])
    manager = ResourceManager(
        args.resource_db,
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(24000),
            (settings.search.provider, "search", "search"): ResourceLimit(30),
        },
    )
    spec = next(
        spec for spec in build_pilot_specs(
            model=args.model,
            search_provider=args.search_provider,
            batch_id=args.run_id.rsplit("_", 2)[0],
        )
        if spec.run_id == args.run_id and spec.group == args.group
    )
    runner = ExperimentRunner(args.root, manager)
    if spec.group == "A":
        def execute(artifact):
            return _run_baseline(
                spec,
                artifact,
                manager,
                TraditionalSearchResearcher(),
                max_tokens=512,
                max_results=1,
            )
    elif spec.group == "B":
        def execute(artifact):
            return _run_baseline(
                spec,
                artifact,
                manager,
                GeneralPurposeAIResearcher(),
                max_tokens=512,
                max_results=1,
            )
    else:
        def execute(artifact):
            return _run_county_research_ai(
                spec,
                artifact,
                manager,
                max_tokens=512,
                max_results=1,
                tasks=["industry_status"],
            )
    manifest = runner.run(spec, execute)
    print(json.dumps({"run_id": manifest.run_id, "status": manifest.status.value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
