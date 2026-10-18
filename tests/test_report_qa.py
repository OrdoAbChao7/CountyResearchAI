from __future__ import annotations

from county_research_ai.evaluation.ground_truth import GroundTruthClaim
from county_research_ai.evaluation.report_qa import (
    build_report_qa_prompt,
    load_frozen_questions,
    score_report_answer,
)


def _claim() -> GroundTruthClaim:
    return GroundTruthClaim(
        claim_id="claim-1",
        claim="2024年地区生产总值为352.6094亿元，按可比价格比上年增长4.9%。",
        source="统计公报",
        url="https://example.gov.cn/bulletin",
        date="2024",
        region="新地区县",
        metric="地区生产总值及同比增速",
        unit="亿元；百分比",
        evidence_excerpt="GDP 352.6094亿元，同比增长4.9%。",
        confidence="high",
        verification_status="VERIFIED",
    )


def test_frozen_report_qa_questions_cover_formal_regions():
    questions = load_frozen_questions()

    assert len(questions) == 6
    assert {question.region for question in questions} == {
        "德清县",
        "长汀县",
        "于都县",
        "攀枝花市",
        "白山市",
        "临泽县",
    }
    assert all(question.claim_id for question in questions)


def test_report_qa_prompt_does_not_include_ground_truth_claim():
    question = load_frozen_questions()[0]

    prompt = build_report_qa_prompt(question, "报告正文")

    assert "报告正文" in prompt
    assert "Ground Truth" not in prompt
    assert "claim_id" not in prompt


def test_report_answer_score_requires_all_frozen_numeric_tokens():
    claim = _claim()

    assert score_report_answer("报告写明 GDP 为352.6094亿元，同比增长4.9%。", claim) == 1.0
    assert score_report_answer("报告只写明 GDP 为352.6094亿元。", claim) == 0.0
    assert score_report_answer("报告未明确说明。", claim) == 0.0
