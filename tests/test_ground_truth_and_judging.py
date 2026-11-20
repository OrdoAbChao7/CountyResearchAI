from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date

import pytest

from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore
from county_research_ai.evaluation.judging import (
    BlindJudge,
    BlindJudgeRunner,
    JudgeScore,
    _judge_prompt,
    calculate_analysis_depth,
    classify_judge_status,
)


def _claim(claim_id: str = "fact-1") -> GroundTruthClaim:
    return GroundTruthClaim(
        claim_id=claim_id,
        claim="产业产值为 10 亿元",
        source="2024统计公报",
        url="https://example.gov.cn/bulletin",
        date="2024-01-01",
        region="新地区县",
        metric="产业产值",
        unit="亿元",
        evidence_excerpt="产业产值为10亿元。",
        confidence="high",
        verification_status="VERIFIED",
    )


def test_ground_truth_roundtrip_and_freeze_hash(tmp_path):
    source = tmp_path / "claims.jsonl"
    GroundTruthStore.write(source, [_claim()])

    bundle = GroundTruthStore.freeze(source)

    assert bundle.claims[0].claim_id == "fact-1"
    assert len(bundle.source_hash) == 64
    assert GroundTruthStore.load(source) == bundle.claims


def test_ground_truth_rejects_duplicate_claim_ids(tmp_path):
    source = tmp_path / "claims.jsonl"
    GroundTruthStore.write(source, [_claim(), _claim("fact-1")])

    with pytest.raises(ValueError, match="duplicate claim_id"):
        GroundTruthStore.load(source)


def test_ground_truth_cross_verification_requires_two_sources():
    with pytest.raises(ValueError, match="two verification sources"):
        GroundTruthStore.validate_cross_verification([_claim()])

    verified = replace(
        _claim(),
        verification_sources=("https://example.gov.cn/bulletin", "https://example.gov.cn/summary"),
        verification_contexts=("independent_context_a", "independent_context_b"),
    )
    GroundTruthStore.validate_cross_verification([verified])


def test_formal_ground_truth_freeze_rejects_unverified_claims(tmp_path):
    source = tmp_path / "claims.jsonl"
    verified = replace(
        _claim(),
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )
    unverified = replace(_claim("fact-2"), verification_status="UNVERIFIED")
    GroundTruthStore.write(source, [verified, unverified])

    with pytest.raises(ValueError, match="UNVERIFIED"):
        GroundTruthStore.freeze(source, require_cross_verification=True)


def test_rich_benchmark_claim_requires_task_matching_fields():
    rich = replace(
        _claim(),
        research_mode="snapshot",
        expected_answer="产业产值为10亿元，统计口径为县域本级",
        source_title="2024年国民经济和社会发展统计公报",
        source_date="2025-03-01",
        metric_year="2024",
        administrative_scope="县域本级",
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )

    GroundTruthStore.validate_rich_claims([rich])


def test_rich_benchmark_claim_rejects_missing_expected_answer():
    rich = replace(
        _claim(),
        research_mode="rise-fall",
        source_title="2024年统计公报",
        source_date="2025-03-01",
        metric_year="2024",
        administrative_scope="县域本级",
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )

    with pytest.raises(ValueError, match="expected_answer"):
        GroundTruthStore.validate_rich_claims([rich])


def test_rich_benchmark_claim_rejects_each_task_matching_field():
    rich = replace(
        _claim(),
        research_mode="snapshot",
        expected_answer="产业产值为10亿元",
        source_title="2024年统计公报",
        source_date="2025-03-01",
        metric_year="2024",
        administrative_scope="县域本级",
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )

    for field in (
        "research_mode",
        "expected_answer",
        "source_title",
        "source_date",
        "metric_year",
        "administrative_scope",
    ):
        with pytest.raises(ValueError, match=field):
            GroundTruthStore.validate_rich_claims([replace(rich, **{field: ""})])


def test_continuation_freeze_requires_rich_claim_manifest(tmp_path):
    source = tmp_path / "claims.jsonl"
    rich = replace(
        _claim(),
        research_mode="snapshot",
        expected_answer="产业产值为10亿元",
        source_title="2024年统计公报",
        source_date="2025-03-01",
        metric_year="2024",
        administrative_scope="县域本级",
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )
    GroundTruthStore.write(source, [rich])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "FROZEN_CONTINUATION_BENCHMARK",
                "source_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    bundle = GroundTruthStore.freeze_continuation_verified(source, manifest)

    assert bundle.claims[0].research_mode == "snapshot"


def test_verified_freeze_rejects_ground_truth_manifest_hash_drift(tmp_path):
    source = tmp_path / "claims.jsonl"
    verified = replace(
        _claim(),
        verification_sources=("https://example.gov.cn/a", "https://example.gov.cn/b"),
        verification_contexts=("context-a", "context-b"),
    )
    GroundTruthStore.write(source, [verified])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "FROZEN_FORMAL_MINIMUM_TARGET",
                "formal_ground_truth": True,
                "source_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    bundle = GroundTruthStore.freeze_verified(
        source, manifest, require_cross_verification=True
    )
    assert bundle.source_hash == json.loads(manifest.read_text(encoding="utf-8"))["source_hash"]

    manifest.write_text(
        json.dumps(
            {
                "status": "FROZEN_FORMAL_MINIMUM_TARGET",
                "formal_ground_truth": True,
                "source_hash": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ground truth manifest hash mismatch"):
        GroundTruthStore.freeze_verified(source, manifest, require_cross_verification=True)


def test_blind_judge_anonymizes_group_and_validates_score_range():
    pack = BlindJudge.anonymize(
        group="C",
        run_id="run-1",
        report="实验组 C 的 run-1 报告\n事实内容",
    )
    score = JudgeScore(
        dimensions={"factual_accuracy": 4, "causal_analysis": 3},
        unsupported_inference_penalty=1,
    )

    assert "实验组 C" not in pack.text
    assert "run-1" not in pack.text
    assert score.mean == 3.5
    with pytest.raises(ValueError):
        JudgeScore(dimensions={"factual_accuracy": 6})


def test_judge_score_accepts_dimension_scores_alias_from_provider():
    score = JudgeScore.from_dict(
        {
            "dimension_scores": {
                "factual_accuracy": 4,
                "key_fact_coverage": 3,
            },
            "unsupported_inference": 1,
        }
    )

    assert score.dimensions["factual_accuracy"] == 4
    assert score.unsupported_inference_penalty == 1


def test_judge_score_accepts_flat_dimension_scores_from_provider():
    score = JudgeScore.from_dict(
        {
            "factual_accuracy": 4,
            "key_fact_coverage": 3,
            "source_reliability": 4,
            "industry_logic": 3,
            "historical_explanation": 2,
            "causal_analysis": 3,
            "structure_completeness": 4,
            "risk_analysis": 2,
            "unsupported_inference": 1,
            "weighted_score": 3.1,
        }
    )

    assert score.dimensions["factual_accuracy"] == 4
    assert score.dimensions["risk_analysis"] == 2
    assert score.unsupported_inference_penalty == 1


def test_judge_score_accepts_nested_scores_and_scores_aliases():
    score = JudgeScore.from_dict(
        {
            "scores": {
                "factual_accuracy": {"score": 4, "rationale": "supported"},
                "risk_analysis": {"score": 2, "rationale": "thin"},
            },
            "unsupported_inference_penalty": 1,
        }
    )

    assert score.dimensions == {"factual_accuracy": 4, "risk_analysis": 2}
    assert score.unsupported_inference_penalty == 1


def test_judge_prompt_serializes_yaml_date_values():
    prompt = _judge_prompt(
        "匿名报告",
        "回答冻结问题",
        {"dimensions": {"cutoff": date(2026, 10, 18)}},
    )

    assert "2026-10-18" in prompt


def test_blind_judge_runner_uses_two_independent_contexts_and_detects_disagreement():
    class FakeJudge:
        def __init__(self, accuracy: int):
            self.accuracy = accuracy

        def chat(self, messages, **kwargs):
            from county_research_ai.llm.base import LLMResponse

            return LLMResponse(
                content=(
                    f'{{"dimensions":{{"factual_accuracy":{self.accuracy},'
                    '"key_fact_coverage":3,"industry_logic":3,'
                    '"historical_explanation":3,"causal_analysis":3,'
                    '"risk_analysis":3,"structure_completeness":3},'
                    '"unsupported_inference_penalty":1}'
                ),
                model="judge-model",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            )

    evaluations = BlindJudgeRunner.run(
        anonymous_report="[GROUP] report",
        task_prompt="回答冻结问题",
        rubric={"dimensions": {"factual_accuracy": {"weight": 0.25}}},
        judges={"judge-a": FakeJudge(5), "judge-b": FakeJudge(2)},
    )

    assert [evaluation.judge_id for evaluation in evaluations] == ["judge-a", "judge-b"]
    assert BlindJudgeRunner.needs_adjudication(evaluations, minimum_gap=2)
    assert calculate_analysis_depth(evaluations) == pytest.approx(3 / 5)


def test_judge_status_keeps_retry_and_adjudication_failures_explicit():
    assert classify_judge_status(completed_judges=1) == "RETRY_REQUIRED"
    assert (
        classify_judge_status(completed_judges=1, retry_attempts=1)
        == "FAILED_JUDGE"
    )
    assert (
        classify_judge_status(
            completed_judges=2,
            adjudication_required=True,
            adjudicator_completed=False,
        )
        == "ADJUDICATION_REQUIRED"
    )
    assert (
        classify_judge_status(
            completed_judges=2,
            adjudication_required=True,
            adjudicator_completed=False,
            adjudicator_failed=True,
        )
        == "FAILED_ADJUDICATION"
    )
