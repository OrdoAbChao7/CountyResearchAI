"""E2 固定输入批次的单组进程入口。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_independent_fixed_input import (
    FORMAL_GATE_PATH,
    FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    FORMAL_GROUND_TRUTH_PATH,
    build_fixed_input_specs,
    load_formal_fixed_input_pack,
)
from scripts.run_independent_smoke import _require_nonempty_report, _smoke_settings

from county_research_ai.evaluation.experiment_agents import (
    CountyResearchAIFixedInputResearcher,
    FixedInputGeneralPurposeAIResearcher,
    FixedInputResearcher,
)
from county_research_ai.evaluation.experiment_models import RunArtifact
from county_research_ai.evaluation.experiment_runner import (
    ExecutionOutcome,
    ExperimentRunner,
    ExperimentRunSpec,
)
from county_research_ai.evaluation.fixed_input import FixedInputPack
from county_research_ai.evaluation.gate import (
    require_formal_api_gate,
    require_frozen_ground_truth,
)
from county_research_ai.evaluation.providers import ResourceManagedLLMClient
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.evaluation.strict_container import StrictRealContainer
from county_research_ai.llm.client import OpenAICompatibleClient


def _artifact_pair(artifact: RunArtifact, name: str):
    path = (artifact.root / name).resolve()
    return path, artifact.sha256(path)


def _run_baseline(
    spec: ExperimentRunSpec,
    pack: FixedInputPack,
    artifact: RunArtifact,
    manager: ResourceManager,
    *,
    researcher: Any,
) -> ExecutionOutcome:
    settings = _smoke_settings(max_tokens=2048, max_results=1, tasks=["industry_status"])
    settings.llm.model = spec.model
    llm = ResourceManagedLLMClient(
        OpenAICompatibleClient(settings=settings),
        manager=manager,
        provider=settings.llm.provider,
        model=settings.llm.model,
        run_id=spec.run_id,
        artifact_dir=artifact.root / "llm_responses",
    )
    result = researcher.run(
        county=pack.region,
        focus=pack.focus,
        mode=pack.mode,
        documents=list(pack.documents),
        llm=llm,
        search=None,
        output_dir=artifact.root,
        input_pack_id=pack.pack_id,
        input_hash=pack.source_hash,
        generation_tokens=2048,
    )
    _require_nonempty_report(result.report)
    pack_path, pack_hash = artifact.write_json("input_pack.json", pack.to_dict())
    return ExecutionOutcome(
        artifacts={
            "input_pack": (pack_path, pack_hash),
            "report": _artifact_pair(artifact, "report.md"),
            "sources": _artifact_pair(artifact, "sources.json"),
        },
        usage_known=result.usage_known and llm.usage_known,
    )


def _run_county_research_ai(
    spec: ExperimentRunSpec,
    pack: FixedInputPack,
    artifact: RunArtifact,
    manager: ResourceManager,
) -> ExecutionOutcome:
    settings = _smoke_settings(max_tokens=2048, max_results=1, tasks=["industry_status"])
    settings.llm.model = spec.model
    settings.storage.data_dir = str(artifact.root / "data")
    settings.storage.reports_dir = str(artifact.root / "generated_reports")
    container = StrictRealContainer.from_settings(
        settings,
        resource_manager=manager,
        run_id=spec.run_id,
        artifact_dir=artifact.root / "llm_responses",
        search_enabled=False,
    )
    result = CountyResearchAIFixedInputResearcher().run(
        pack=pack,
        container=container,
        output_dir=artifact.root,
    )
    pack_path, pack_hash = artifact.write_json("input_pack.json", pack.to_dict())
    return ExecutionOutcome(
        artifacts={
            "input_pack": (pack_path, pack_hash),
            "report": _artifact_pair(artifact, "report.md"),
            "sources": _artifact_pair(artifact, "sources.json"),
        },
        usage_known=result.usage_known,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-db", type=Path, required=True)
    parser.add_argument("--input-pack", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--group", choices=["A", "B", "C"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    require_formal_api_gate(FORMAL_GATE_PATH)
    require_frozen_ground_truth(
        FORMAL_GROUND_TRUTH_PATH,
        FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    )
    pack = load_formal_fixed_input_pack(args.input_pack)
    settings = _smoke_settings(max_tokens=2048, max_results=1, tasks=["industry_status"])
    settings.llm.model = args.model
    manager = ResourceManager(
        args.resource_db,
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(
                24000,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider == "deepseek"
                    else "free_confirmed"
                ),
            ),
        },
    )
    spec = next(
        item
        for item in build_fixed_input_specs(
            pack=pack,
            model=args.model,
            batch_id=args.batch_id,
        )
        if item.run_id == args.run_id and item.group == args.group
    )
    runner = ExperimentRunner(args.root, manager)
    if spec.group in {"A", "B"}:
        researcher = (
            FixedInputResearcher()
            if spec.group == "A"
            else FixedInputGeneralPurposeAIResearcher()
        )

        def execute(artifact):
            return _run_baseline(
                spec,
                pack,
                artifact,
                manager,
                researcher=researcher,
            )
    else:

        def execute(artifact):
            return _run_county_research_ai(spec, pack, artifact, manager)

    manifest = runner.run(spec, execute)
    print(json.dumps({"run_id": manifest.run_id, "status": manifest.status.value}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
