"""运行最小真实 A/B/C Smoke Test。

该脚本使用当前配置的真实 Provider；DeepSeek Search/Fetch 仍受显式 opt-in 和正式 gate 约束。所有运行先写
PLANNED/RUNNING Manifest，真实 Provider 失败或 usage 缺失会保留为无效样本。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from county_research_ai.config import load_settings
from county_research_ai.evaluation.experiment_agents import (
    GeneralPurposeAIResearcher,
    TraditionalSearchResearcher,
)
from county_research_ai.evaluation.experiment_models import RunArtifact
from county_research_ai.evaluation.experiment_runner import (
    ExecutionOutcome,
    ExperimentRunner,
    ExperimentRunSpec,
)
from county_research_ai.evaluation.providers import (
    ResourceManagedLLMClient,
    ResourceManagedSearchProvider,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.evaluation.strict_container import StrictRealContainer
from county_research_ai.llm.client import OpenAICompatibleClient
from county_research_ai.models import ResearchRequest
from county_research_ai.search.web_search import create_provider


def build_smoke_specs(*, model: str, search_provider: str, batch_id: str) -> list[ExperimentRunSpec]:
    specs: list[ExperimentRunSpec] = []
    for county in ("安吉县", "信丰县"):
        focus = "竹产业" if county == "安吉县" else "脐橙产业"
        for group in ("A", "B", "C"):
            run_id = f"{batch_id}_{county}_{group}"
            specs.append(
                ExperimentRunSpec(
                    run_id=run_id,
                    experiment_id="E1",
                    group=group,
                    county=county,
                    task_id="snapshot",
                    mode="snapshot",
                    model=model,
                    search_provider=search_provider,
                    config={
                        "batch_id": batch_id,
                        "model": model,
                        "search_provider": search_provider,
                        "group": group,
                        "county": county,
                        "focus": focus,
                        "max_llm_tokens": 2048,
                        "max_tavily_requests": 120,
                    },
                )
            )
    return specs


def build_c_probe_spec(*, model: str, search_provider: str, batch_id: str) -> ExperimentRunSpec:
    return ExperimentRunSpec(
        run_id=f"{batch_id}_安吉县_C",
        experiment_id="E1",
        group="C",
        county="安吉县",
        task_id="snapshot",
        mode="snapshot",
        model=model,
        search_provider=search_provider,
        config={
            "batch_id": batch_id,
            "model": model,
            "search_provider": search_provider,
            "group": "C",
            "county": "安吉县",
            "focus": "竹产业",
            "max_llm_tokens": 512,
            "max_search_results": 1,
            "llm_tasks": ["industry_status"],
        },
    )


def build_pilot_specs(*, model: str, search_provider: str, batch_id: str) -> list[ExperimentRunSpec]:
    """为一个未参与开发调试的地区构造低预算 A/B/C 先导批次。"""
    return [
        ExperimentRunSpec(
            run_id=f"{batch_id}_于都县_{group}",
            experiment_id="E1",
            group=group,
            county="于都县",
            task_id="snapshot",
            mode="snapshot",
            model=model,
            search_provider=search_provider,
            config={
                "batch_id": batch_id,
                "model": model,
                "search_provider": search_provider,
                "group": group,
                "county": "于都县",
                "focus": "电子信息与纺织服装",
                "max_llm_tokens": 512,
                "max_search_results": 1,
                "max_tavily_requests": 30,
                "llm_tasks": ["industry_status"],
                "pilot": True,
            },
        )
        for group in ("A", "B", "C")
    ]


def _smoke_settings(
    *,
    max_tokens: int = 2048,
    max_results: int = 3,
    tasks: list[str] | None = None,
):
    settings = load_settings()
    settings.llm.max_tokens = max_tokens
    if tasks is not None:
        settings.llm.tasks = tasks
    settings.search.max_results = max_results
    settings.search.concurrency = 1
    settings.search.fetch_detail = False
    settings.pipeline.fail_fast = True
    return settings


def _artifact_pair(artifact: RunArtifact, name: str) -> tuple[Path, str]:
    path = (artifact.root / name).resolve()
    return path, artifact.sha256(path)


def _require_nonempty_report(report: str) -> str:
    if not isinstance(report, str) or not report.strip():
        raise ValueError("researcher returned an empty report")
    return report


def _focus_for_spec(spec: ExperimentRunSpec) -> str:
    configured = spec.config.get("focus")
    if configured:
        return str(configured)
    return "竹产业" if spec.county == "安吉县" else "脐橙产业"


def _build_experiment_search(settings, spec: ExperimentRunSpec, manager: ResourceManager):
    """Construct the search provider named by the frozen run specification."""
    settings.search.provider = spec.search_provider
    provider = create_provider(provider=spec.search_provider, settings=settings)
    return ResourceManagedSearchProvider(
        provider,
        manager=manager,
        provider=spec.search_provider,
        run_id=spec.run_id,
    )


def _instrumented_usage_known(container: StrictRealContainer) -> bool:
    """只接受严格容器中实际 instrumented LLM 返回的 Usage 状态。"""
    instrumented_llm = getattr(container, "instrumented_llm", None)
    return bool(instrumented_llm is not None and instrumented_llm.usage_known)


def _run_baseline(
    spec: ExperimentRunSpec,
    artifact: RunArtifact,
    manager: ResourceManager,
    researcher: Any,
    *,
    max_tokens: int = 2048,
    max_results: int = 3,
) -> ExecutionOutcome:
    settings = _smoke_settings(max_tokens=max_tokens, max_results=max_results)
    settings.llm.model = spec.model
    llm = ResourceManagedLLMClient(
        OpenAICompatibleClient(settings=settings),
        manager=manager,
        provider=settings.llm.provider,
        model=settings.llm.model,
        run_id=spec.run_id,
        artifact_dir=artifact.root / "llm_responses",
    )
    search = _build_experiment_search(settings, spec, manager)
    focus = _focus_for_spec(spec)
    run_kwargs = {
        "county": spec.county,
        "focus": focus,
        "mode": spec.mode,
        "llm": llm,
        "search": search,
        "output_dir": artifact.root,
    }
    if isinstance(researcher, TraditionalSearchResearcher):
        result = researcher.run(
            **run_kwargs,
            generation_tokens=max_tokens,
            max_results=max_results,
        )
    else:
        result = researcher.run(
            **run_kwargs,
            planning_tokens=min(256, max_tokens),
            generation_tokens=max_tokens,
            max_results=max_results,
        )
    _require_nonempty_report(result.report)
    return ExecutionOutcome(
        artifacts={
            "report": _artifact_pair(artifact, "report.md"),
            "sources": _artifact_pair(artifact, "sources.json"),
        },
        usage_known=result.usage_known,
    )


def _run_county_research_ai(
    spec: ExperimentRunSpec,
    artifact: RunArtifact,
    manager: ResourceManager,
    *,
    max_tokens: int = 2048,
    max_results: int = 3,
    tasks: list[str] | None = None,
) -> ExecutionOutcome:
    settings = _smoke_settings(max_tokens=max_tokens, max_results=max_results, tasks=tasks)
    settings.storage.data_dir = str(artifact.root / "data")
    settings.storage.reports_dir = str(artifact.root / "generated_reports")
    container = StrictRealContainer.from_settings(
        settings,
        resource_manager=manager,
        run_id=spec.run_id,
        artifact_dir=artifact.root / "llm_responses",
    )
    focus = _focus_for_spec(spec)
    result = container.app.workflow.run(
        ResearchRequest(
            county=spec.county,
            focus=focus,
            mode=spec.mode,
            options={"no_cache": True},
        )
    )
    report_path, _ = artifact.write_text("report.md", result.report_path.read_text(encoding="utf-8"))
    sources_path, _ = artifact.write_json(
        "sources.json",
        {
            "report_path": str(result.report_path),
            "sections": [section.title for section in result.report.sections],
        },
    )
    return ExecutionOutcome(
        artifacts={
            "report": (report_path, artifact.sha256(report_path)),
            "sources": (sources_path, artifact.sha256(sources_path)),
        },
        usage_known=_instrumented_usage_known(container),
    )


def run_smoke(batch_id: str | None = None) -> dict[str, str]:
    settings = _smoke_settings()
    batch_id = batch_id or datetime.now(timezone.utc).strftime("smoke_%Y%m%dT%H%M%SZ")
    root = Path("experiments/independent_comparison/runs") / batch_id
    manager = ResourceManager(
        root / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(40000),
            (settings.search.provider, "search", "search"): ResourceLimit(120),
        },
    )
    runner = ExperimentRunner(root, manager)
    results: dict[str, str] = {}
    for spec in build_smoke_specs(
        model=settings.llm.model,
        search_provider=settings.search.provider,
        batch_id=batch_id,
    ):
        if spec.group == "A":
            def execute(artifact, current=spec):
                return _run_baseline(current, artifact, manager, TraditionalSearchResearcher())
        elif spec.group == "B":
            def execute(artifact, current=spec):
                return _run_baseline(current, artifact, manager, GeneralPurposeAIResearcher())
        else:
            def execute(artifact, current=spec):
                return _run_county_research_ai(current, artifact, manager)
        manifest = runner.run(spec, execute)
        results[spec.run_id] = manifest.status.value
        print(json.dumps({"run_id": spec.run_id, "status": manifest.status.value}, ensure_ascii=False))
    (root / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def run_c_probe(batch_id: str | None = None) -> str:
    settings = _smoke_settings(max_tokens=512, max_results=1, tasks=["industry_status"])
    batch_id = batch_id or datetime.now(timezone.utc).strftime("c_probe_%Y%m%dT%H%M%SZ")
    root = Path("experiments/independent_comparison/runs") / batch_id
    manager = ResourceManager(
        root / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(12000),
            (settings.search.provider, "search", "search"): ResourceLimit(40),
        },
    )
    spec = build_c_probe_spec(
        model=settings.llm.model,
        search_provider=settings.search.provider,
        batch_id=batch_id,
    )
    runner = ExperimentRunner(root, manager)

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
    print(json.dumps({"run_id": spec.run_id, "status": manifest.status.value}, ensure_ascii=False))
    return manifest.status.value


def run_pilot(batch_id: str | None = None) -> dict[str, str]:
    """执行单个新地区的低预算 A/B/C 先导，不宣称正式质量结论。"""
    settings = _smoke_settings(max_tokens=512, max_results=1, tasks=["industry_status"])
    batch_id = batch_id or datetime.now(timezone.utc).strftime("pilot_%Y%m%dT%H%M%SZ")
    root = Path("experiments/independent_comparison/runs") / batch_id
    ResourceManager(
        root / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(24000),
            (settings.search.provider, "search", "search"): ResourceLimit(30),
        },
    )
    results: dict[str, str] = {}
    for spec in build_pilot_specs(
        model=settings.llm.model,
        search_provider=settings.search.provider,
        batch_id=batch_id,
    ):
        subprocess.run(
            _pilot_worker_command(spec, root),
            cwd=Path(__file__).resolve().parents[1],
            check=True,
        )
        manifest = json.loads(
            (root / spec.run_id / "manifest.json").read_text(encoding="utf-8")
        )
        results[spec.run_id] = manifest["status"]
    (root / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def _pilot_worker_command(spec: ExperimentRunSpec, root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.run_independent_worker",
        "--root",
        str(root.resolve()),
        "--resource-db",
        str((root / "resources.sqlite").resolve()),
        "--run-id",
        spec.run_id,
        "--group",
        spec.group,
        "--model",
        spec.model,
        "--search-provider",
        spec.search_provider,
    ]


if __name__ == "__main__":
    run_smoke()
