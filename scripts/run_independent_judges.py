"""对 VALID 独立运行执行匿名盲评。

该入口不把失败运行补成评分结果。它先校验 Manifest 和报告哈希，再将报告
匿名化；真正的 Judge API 调用必须通过 formal gate，并单独按 kind=judge 记账。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from county_research_ai.config import load_settings
from county_research_ai.evaluation.gate import require_formal_api_gate
from county_research_ai.evaluation.judging import (
    AnonymousReport,
    BlindJudge,
    BlindJudgeRunner,
    calculate_analysis_depth,
)
from county_research_ai.evaluation.providers import ResourceManagedJudgeClient
from county_research_ai.evaluation.reporting import load_manifests, validate_manifest_artifacts
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.exceptions import LLMError
from county_research_ai.llm.client import OpenAICompatibleClient

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
RUBRIC_PATH = FORMAL_ROOT / "protocol" / "rubric.yaml"
FORMAL_GATE_PATH = FORMAL_ROOT / "manifests" / "formal_target_gate_20261018.json"


@dataclass(frozen=True)
class JudgeCandidate:
    run_id: str
    group: str
    county: str
    task_id: str
    run_dir: Path
    anonymous_report: AnonymousReport
    repeat: int = 1
    duration_seconds: float | None = None
    research_resource_usage: dict[str, int] | None = None

    @property
    def task_prompt(self) -> str:
        return f"评价{self.county}的{self.task_id}研究报告，按冻结 Rubric 对各维度评分。"


def load_frozen_rubric(path: Path = RUBRIC_PATH) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") != "FROZEN":
        raise ValueError("blind-judge rubric must be explicitly FROZEN")
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("blind-judge rubric must define dimensions")
    policy = value.get("judge_policy")
    if not isinstance(policy, dict) or int(policy.get("minimum_independent_judges", 0)) < 2:
        raise ValueError("rubric must require at least two independent judges")
    return value


def collect_judge_candidates(
    runs_root: Path,
    *,
    max_runs: int | None = None,
    run_id_prefixes: tuple[str, ...] | None = None,
) -> list[JudgeCandidate]:
    candidates: list[JudgeCandidate] = []
    for manifest in load_manifests(runs_root):
        if manifest.get("status") != "VALID" or manifest.get("formal_target") is not True:
            continue
        run_id = str(manifest.get("run_id", ""))
        if "preflight" in run_id.lower():
            continue
        if run_id_prefixes and not any(run_id.startswith(prefix) for prefix in run_id_prefixes):
            continue
        manifest_path = Path(manifest["_manifest_path"])
        run_dir = manifest_path.parent
        validate_manifest_artifacts(manifest, run_dir)
        declaration = manifest.get("artifacts", {}).get("report")
        if not isinstance(declaration, str) or ":" not in declaration:
            raise ValueError(f"VALID run has no report artifact: {manifest.get('run_id')}")
        relative, _ = declaration.rsplit(":", 1)
        report_path = (run_dir / relative).resolve()
        if run_dir.resolve() not in report_path.parents or not report_path.is_file():
            raise ValueError(f"report artifact is outside or missing: {manifest.get('run_id')}")
        report = report_path.read_text(encoding="utf-8")
        candidates.append(
            JudgeCandidate(
                run_id=run_id,
                group=str(manifest["group"]),
                county=str(manifest["county"]),
                task_id=str(manifest.get("task_id", manifest.get("mode", "unknown"))),
                run_dir=run_dir,
                anonymous_report=BlindJudge.anonymize(
                    group=str(manifest["group"]),
                    run_id=run_id,
                    report=report,
                ),
                repeat=_repeat_from_run_id(str(manifest["run_id"])),
                duration_seconds=manifest.get("duration_seconds"),
                research_resource_usage={
                    str(key): int(amount)
                    for key, amount in dict(manifest.get("resource_usage", {})).items()
                },
            )
        )
    candidates.sort(key=lambda item: item.run_id)
    return candidates[:max_runs] if max_runs is not None else candidates


def _repeat_from_run_id(run_id: str) -> int:
    match = re.search(r"_r(\d+)_[ABC]$", run_id)
    return int(match.group(1)) if match else 1


def _write_anonymous_inputs(candidates: list[JudgeCandidate], output_dir: Path) -> None:
    anonymous_dir = output_dir / "anonymous_reports"
    anonymous_dir.mkdir(parents=True, exist_ok=True)
    private_index: list[dict[str, str]] = []
    for candidate in candidates:
        path = anonymous_dir / f"{candidate.anonymous_report.report_hash}.md"
        path.write_text(candidate.anonymous_report.text, encoding="utf-8")
        private_index.append(
            {
                "run_id": candidate.run_id,
                "group": candidate.group,
                "county": candidate.county,
                "task_id": candidate.task_id,
                "anonymous_report_hash": candidate.anonymous_report.report_hash,
            }
        )
    (output_dir / "blind_index_private.json").write_text(
        json.dumps(private_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resource_usage(manager: ResourceManager, run_prefix: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for event in manager.snapshot().events:
        if not str(event["run_id"]).startswith(run_prefix):
            continue
        if event["status"] == "reserved":
            continue
        key = f"{event['provider']}:{event['model']}:{event['kind']}"
        usage[key] = usage.get(key, 0) + int(event["units"])
    return dict(sorted(usage.items()))


def run_judge_batch(
    *,
    runs_root: Path,
    output_dir: Path,
    batch_id: str,
    max_runs: int | None = None,
    run_id_prefixes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    rubric = load_frozen_rubric()
    candidates = collect_judge_candidates(
        runs_root,
        max_runs=max_runs,
        run_id_prefixes=run_id_prefixes,
    )
    if not candidates:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {"status": "NO_VALID_RUNS", "candidates": 0, "judgements": 0}
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    require_formal_api_gate(FORMAL_GATE_PATH)
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_anonymous_inputs(candidates, output_dir)
    settings = load_settings()
    max_calls = len(candidates) * 3
    manager = ResourceManager(
        output_dir / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "judge"): ResourceLimit(
                max_calls * 8192,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider == "deepseek"
                    else "free_confirmed"
                ),
            )
        },
    )
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.anonymous_report.text.strip():
            rows.append(
                {
                    "status": "FAILED_EMPTY_REPORT",
                    "run_id": candidate.run_id,
                    "anonymous_report_hash": candidate.anonymous_report.report_hash,
                    "judge_evaluations": [],
                    "analysis_depth": None,
                    "adjudication_required": False,
                    "judge_errors": [
                        {
                            "judge_id": "all",
                            "error_type": "EMPTY_REPORT",
                            "error": "anonymous report is empty",
                        }
                    ],
                    "resource_usage": {},
                }
            )
            continue
        clients = {
            judge_id: ResourceManagedJudgeClient(
                OpenAICompatibleClient(settings=settings),
                manager=manager,
                provider=settings.llm.provider,
                model=settings.llm.model,
                run_id=f"{batch_id}_{candidate.anonymous_report.report_hash}_{judge_id}",
                artifact_dir=output_dir / "raw_responses" / judge_id / candidate.run_id,
            )
            for judge_id in ("judge_1", "judge_2")
        }
        evaluations = []
        judge_errors: list[dict[str, str]] = []
        for judge_id, client in clients.items():
            try:
                evaluations.append(
                    BlindJudgeRunner.evaluate_one(
                        anonymous_report=candidate.anonymous_report.text,
                        task_prompt=candidate.task_prompt,
                        rubric=rubric,
                        judge_id=judge_id,
                        client=client,
                    )
                )
            except (LLMError, ValueError) as exc:
                judge_errors.append(
                    {
                        "judge_id": judge_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        adjudication_required = len(evaluations) >= 2 and BlindJudgeRunner.needs_adjudication(
            evaluations,
            minimum_gap=int(
                rubric["judge_policy"].get(
                    "adjudication_required_if_absolute_dimension_gap_at_least", 2
                )
            ),
        )
        adjudicator_failed = False
        if adjudication_required:
            judge_id = "adjudicator"
            adjudicator = ResourceManagedJudgeClient(
                OpenAICompatibleClient(settings=settings),
                manager=manager,
                provider=settings.llm.provider,
                model=settings.llm.model,
                run_id=f"{batch_id}_{candidate.anonymous_report.report_hash}_{judge_id}",
                artifact_dir=output_dir / "raw_responses" / judge_id / candidate.run_id,
            )
            try:
                evaluations.append(
                    BlindJudgeRunner.evaluate_one(
                        anonymous_report=candidate.anonymous_report.text,
                        task_prompt=candidate.task_prompt,
                        rubric=rubric,
                        judge_id=judge_id,
                        client=adjudicator,
                    )
                )
            except (LLMError, ValueError) as exc:
                adjudicator_failed = True
                judge_errors.append(
                    {
                        "judge_id": judge_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        valid = len(evaluations) >= 2 and not adjudicator_failed
        rows.append(
            {
                "status": "VALID" if valid else "FAILED_JUDGE",
                "run_id": candidate.run_id,
                "anonymous_report_hash": candidate.anonymous_report.report_hash,
                "judge_evaluations": [
                    {
                        "judge_id": evaluation.judge_id,
                        "score": evaluation.score.to_dict(),
                        "raw_response": evaluation.raw_response,
                    }
                    for evaluation in evaluations
                ],
                "analysis_depth": calculate_analysis_depth(evaluations),
                "adjudication_required": adjudication_required,
                "judge_errors": judge_errors,
                "resource_usage": _resource_usage(
                    manager, f"{batch_id}_{candidate.anonymous_report.report_hash}_"
                ),
            }
        )
    (output_dir / "judgements.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "status": "OK",
        "candidates": len(candidates),
        "judgements": len(rows),
        "valid_judgements": sum(1 for row in rows if row["status"] == "VALID"),
        "failed_judgements": sum(1 for row in rows if row["status"] != "VALID"),
        "adjudications": sum(1 for row in rows if row["adjudication_required"]),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-id", default="judges_20261018")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--run-id-prefix", action="append", dest="run_id_prefixes")
    args = parser.parse_args()
    print(
        json.dumps(
            run_judge_batch(
                runs_root=args.runs_root,
                output_dir=args.output_dir,
                batch_id=args.batch_id,
                max_runs=args.max_runs,
                run_id_prefixes=tuple(args.run_id_prefixes or ()),
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
