"""只基于研究报告的冻结问题和保守答案评分。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .ground_truth import GroundTruthClaim

QA_PATH = (
    Path(__file__).resolve().parents[3]
    / "experiments"
    / "independent_comparison"
    / "protocol"
    / "report_qa_questions_20261018.yaml"
)
_NUMBER_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?%?")


@dataclass(frozen=True)
class ReportQAQuestion:
    question_id: str
    region: str
    claim_id: str
    prompt: str


def load_frozen_questions(path: Path = QA_PATH) -> list[ReportQAQuestion]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") != "FROZEN":
        raise ValueError("report-based QA questions must be explicitly FROZEN")
    raw_questions = value.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("report-based QA question list is required")
    questions: list[ReportQAQuestion] = []
    seen: set[str] = set()
    for item in raw_questions:
        if not isinstance(item, dict):
            raise ValueError("report-based QA question must be an object")
        question = ReportQAQuestion(
            question_id=str(item.get("question_id", "")),
            region=str(item.get("region", "")),
            claim_id=str(item.get("claim_id", "")),
            prompt=str(item.get("prompt", "")),
        )
        if not all((question.question_id, question.region, question.claim_id, question.prompt)):
            raise ValueError("report-based QA question fields are required")
        if question.question_id in seen:
            raise ValueError(f"duplicate report-based QA question: {question.question_id}")
        seen.add(question.question_id)
        questions.append(question)
    return questions


def build_report_qa_prompt(question: ReportQAQuestion, report: str) -> str:
    """构造答案 Agent 输入；不包含 claim、Ground Truth 或组别信息。"""
    return (
        "你是独立的报告型问答 Agent。只能依据给定研究报告回答问题，不能使用外部知识、"
        "其他报告或实验过程。若报告没有明确回答，必须明确写‘报告未明确说明’。只输出 JSON，"
        "字段为 answer 和 supporting_excerpt。\n"
        f"问题：{question.prompt}\n"
        f"研究报告：\n{report}"
    )


def score_report_answer(answer: str, claim: GroundTruthClaim) -> float:
    """对冻结数字 claim 做保守的报告支持评分。

    该评分器只检查冻结 claim 中的非年份数字是否全部出现在答案中；它不是事实核验器，
    也不把部分匹配提升为正确，适合在正式 LLM Judge/Claim Verifier 之外作为 QA 指标。
    """
    normalized_answer = str(answer).replace("％", "%")
    expected = [token for token in _NUMBER_RE.findall(claim.claim) if not _is_year(token)]
    if not expected:
        return 0.0
    return 1.0 if all(token in normalized_answer for token in expected) else 0.0


def _is_year(token: str) -> bool:
    if token.endswith("%") or "." in token:
        return False
    try:
        value = int(token)
    except ValueError:
        return False
    return 1900 <= value <= 2100
