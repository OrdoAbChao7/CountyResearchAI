"""执行只基于研究报告的冻结问题 QA，并生成可重算 QA 指标。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_independent_judges import JudgeCandidate, collect_judge_candidates

from county_research_ai.config import load_settings
from county_research_ai.evaluation.gate import require_formal_api_gate
from county_research_ai.evaluation.ground_truth import GroundTruthStore
from county_research_ai.evaluation.providers import ResourceManagedLLMClient
from county_research_ai.evaluation.report_qa import (
    ReportQAQuestion,
    build_report_qa_prompt,
    load_frozen_questions,
    score_report_answer,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager
from county_research_ai.llm.client import OpenAICompatibleClient

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
FORMAL_GATE_PATH = FORMAL_ROOT / "manifests" / "formal_target_gate_20261018.json"
FORMAL_GROUND_TRUTH_PATH = FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018.jsonl"
FORMAL_GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018_manifest.json"
)


def build_qa_pairs(
    candidates: list[JudgeCandidate], questions: list[ReportQAQuestion]
) -> list[tuple[JudgeCandidate, ReportQAQuestion]]:
    by_region = {question.region: question for question in questions}
    pairs: list[tuple[JudgeCandidate, ReportQAQuestion]] = []
    for candidate in candidates:
        question = by_region.get(candidate.county)
        if question is not None:
            pairs.append((candidate, question))
    return pairs


def parse_qa_response(content: str) -> tuple[str, str]:
    try:
        value = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "", ""
    if not isinstance(value, dict):
        return "", ""
    answer = value.get("answer")
    excerpt = value.get("supporting_excerpt", "")
    if not isinstance(answer, str) or not answer.strip():
        return "", ""
    return answer.strip(), str(excerpt).strip()


def _resource_usage(manager: ResourceManager, run_id: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for event in manager.snapshot().events:
        if event["run_id"] != run_id or event["status"] == "reserved":
            continue
        key = f"{event['provider']}:{event['model']}:{event['kind']}"
        usage[key] = usage.get(key, 0) + int(event["units"])
    return dict(sorted(usage.items()))


def run_qa_batch(
    *,
    runs_root: Path,
    output_dir: Path,
    batch_id: str,
    max_runs: int | None = None,
    run_id_prefixes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    questions = load_frozen_questions()
    claims = {
        claim.claim_id: claim
        for claim in GroundTruthStore.freeze_verified(
            FORMAL_GROUND_TRUTH_PATH,
            FORMAL_GROUND_TRUTH_MANIFEST_PATH,
            require_cross_verification=True,
        ).claims
    }
    if any(question.claim_id not in claims for question in questions):
        raise ValueError("report-based QA references a missing formal Ground Truth claim")
    pairs = build_qa_pairs(
        collect_judge_candidates(
            runs_root,
            max_runs=max_runs,
            run_id_prefixes=run_id_prefixes,
        ),
        questions,
    )
    if not pairs:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {"status": "NO_VALID_QA_INPUTS", "pairs": 0, "scored": 0}
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    require_formal_api_gate(FORMAL_GATE_PATH)
    output_dir.mkdir(parents=True, exist_ok=False)
    settings = load_settings()
    manager = ResourceManager(
        output_dir / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "qa"): ResourceLimit(
                len(pairs) * 8192,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider == "deepseek"
                    else "free_confirmed"
                ),
            )
        },
    )
    rows: list[dict[str, Any]] = []
    for candidate, question in pairs:
        qa_run_id = f"{batch_id}_{candidate.anonymous_report.report_hash}_{question.question_id}"
        client = ResourceManagedLLMClient(
            OpenAICompatibleClient(settings=settings),
            manager=manager,
            provider=settings.llm.provider,
            model=settings.llm.model,
            run_id=qa_run_id,
            artifact_dir=output_dir / "raw_responses" / candidate.run_id / question.question_id,
            resource_kind="qa",
        )
        response = client.chat(
            [{
                "role": "user",
                "content": build_report_qa_prompt(question, candidate.anonymous_report.text),
            }],
            max_tokens=1024,
            temperature=0.0,
        )
        answer, excerpt = parse_qa_response(response.content)
        parsed = bool(answer)
        rows.append(
            {
                "status": "VALID" if client.usage_known else "INVALID_USAGE_UNKNOWN",
                "run_id": candidate.run_id,
                "question_id": question.question_id,
                "region": question.region,
                "claim_id": question.claim_id,
                "answer": answer,
                "supporting_excerpt": excerpt,
                "answer_parse_status": "VALID" if parsed else "INVALID",
                "qa_accuracy": score_report_answer(answer, claims[question.claim_id]) if parsed else 0.0,
                "resource_usage": _resource_usage(manager, qa_run_id),
                "raw_response": response.content,
            }
        )
    (output_dir / "qa_observations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "status": "OK",
        "pairs": len(pairs),
        "scored": sum(1 for row in rows if row["answer_parse_status"] == "VALID"),
        "mean_qa_accuracy": sum(float(row["qa_accuracy"]) for row in rows) / len(rows),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-id", default="report_qa_20261018")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--run-id-prefix", action="append", dest="run_id_prefixes")
    args = parser.parse_args()
    print(
        json.dumps(
            run_qa_batch(
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
