"""匿名报告打包和盲评分数模型。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class AnonymousReport:
    text: str
    report_hash: str


@dataclass(frozen=True)
class JudgeScore:
    dimensions: dict[str, int]
    unsupported_inference_penalty: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 or value > 5 for value in self.dimensions.values()):
            raise ValueError("judge dimension scores must be between 0 and 5")
        if self.unsupported_inference_penalty < 0:
            raise ValueError("unsupported inference penalty must not be negative")

    @property
    def mean(self) -> float:
        return sum(self.dimensions.values()) / len(self.dimensions) if self.dimensions else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": dict(self.dimensions),
            "unsupported_inference_penalty": self.unsupported_inference_penalty,
            "mean": self.mean,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> JudgeScore:
        dimensions = value.get(
            "dimensions",
            value.get("dimension_scores", value.get("scores")),
        )
        if isinstance(dimensions, dict):
            dimensions = {
                name: item.get("score") if isinstance(item, dict) else item
                for name, item in dimensions.items()
            }
        if not isinstance(dimensions, dict):
            dimension_names = {
                "factual_accuracy",
                "key_fact_coverage",
                "source_reliability",
                "industry_logic",
                "historical_explanation",
                "causal_analysis",
                "structure_completeness",
                "risk_analysis",
                "unsupported_inference",
            }
            dimensions = {
                name: value[name]
                for name in dimension_names
                if name in value
            }
        if not isinstance(dimensions, dict) or not dimensions:
            raise ValueError("judge response must contain non-empty dimensions")
        penalty = value.get("unsupported_inference_penalty")
        if penalty is None:
            penalty = value.get("unsupported_inference", 0)
        if isinstance(penalty, dict):
            penalty = penalty.get("score", 0)
        return cls(
            dimensions={str(name): int(score) for name, score in dimensions.items()},
            unsupported_inference_penalty=int(penalty),
        )


@dataclass(frozen=True)
class JudgeEvaluation:
    judge_id: str
    score: JudgeScore
    raw_response: str


class BlindJudge:
    @staticmethod
    def anonymize(*, group: str, run_id: str, report: str) -> AnonymousReport:
        text = report.replace(group, "[GROUP]").replace(run_id, "[RUN]")
        text = re.sub(r"(?i)(实验组|group)\s*[A-F]", "[GROUP]", text)
        text = re.sub(r"(?i)run[-_][a-z0-9-]+", "[RUN]", text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return AnonymousReport(text=text, report_hash=digest)


class BlindJudgeRunner:
    """在独立客户端上下文中运行多个盲评 Agent。"""

    @staticmethod
    def evaluate_one(
        *,
        anonymous_report: str,
        task_prompt: str,
        rubric: dict[str, Any],
        judge_id: str,
        client: Any,
    ) -> JudgeEvaluation:
        prompt = _judge_prompt(anonymous_report, task_prompt, rubric)
        response = client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.0,
        )
        try:
            payload = json.loads(response.content)
            score = JudgeScore.from_dict(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid blind judge response from {judge_id}") from exc
        return JudgeEvaluation(judge_id=judge_id, score=score, raw_response=response.content)

    @staticmethod
    def run(
        *,
        anonymous_report: str,
        task_prompt: str,
        rubric: dict[str, Any],
        judges: dict[str, Any],
    ) -> list[JudgeEvaluation]:
        if len(judges) < 2:
            raise ValueError("at least two independent judges are required")
        return [
            BlindJudgeRunner.evaluate_one(
                anonymous_report=anonymous_report,
                task_prompt=task_prompt,
                rubric=rubric,
                judge_id=judge_id,
                client=client,
            )
            for judge_id, client in judges.items()
        ]

    @staticmethod
    def needs_adjudication(
        evaluations: list[JudgeEvaluation], *, minimum_gap: int = 2
    ) -> bool:
        if len(evaluations) < 2:
            return False
        dimensions = set.intersection(
            *(set(evaluation.score.dimensions) for evaluation in evaluations)
        )
        return any(
            max(evaluation.score.dimensions[name] for evaluation in evaluations)
            - min(evaluation.score.dimensions[name] for evaluation in evaluations)
            >= minimum_gap
            for name in dimensions
        )


def calculate_analysis_depth(evaluations: list[JudgeEvaluation]) -> float | None:
    """把冻结 Rubric 的分析维度汇总为 0–1 之间的深度指标。"""
    dimensions = (
        "industry_logic",
        "historical_explanation",
        "causal_analysis",
        "risk_analysis",
        "structure_completeness",
    )
    values = [
        evaluation.score.dimensions[name]
        for evaluation in evaluations
        for name in dimensions
        if name in evaluation.score.dimensions
    ]
    return mean(values) / 5 if values else None


def _judge_prompt(anonymous_report: str, task_prompt: str, rubric: dict[str, Any]) -> str:
    return (
        "你是独立盲评 Agent。不要猜测实验组、运行编号或其他报告。"
        "只根据任务、冻结 Rubric 和匿名报告评分；只输出 JSON。\n"
        f"任务：{task_prompt}\nRubric：{json.dumps(rubric, ensure_ascii=False, default=str)}\n"
        f"匿名报告：\n{anonymous_report}"
    )
