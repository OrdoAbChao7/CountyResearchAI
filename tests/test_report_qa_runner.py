from __future__ import annotations

from pathlib import Path

from scripts.run_independent_judges import JudgeCandidate
from scripts.run_independent_report_qa import build_qa_pairs, parse_qa_response

from county_research_ai.evaluation.judging import AnonymousReport
from county_research_ai.evaluation.report_qa import load_frozen_questions


def _candidate(region: str) -> JudgeCandidate:
    return JudgeCandidate(
        run_id="run-1",
        group="C",
        county=region,
        task_id="snapshot",
        run_dir=Path("."),
        anonymous_report=AnonymousReport(text="匿名报告", report_hash="a" * 64),
    )


def test_build_qa_pairs_matches_only_the_candidate_region():
    pairs = build_qa_pairs([_candidate("德清县")], load_frozen_questions())

    assert len(pairs) == 1
    assert pairs[0][0].county == "德清县"
    assert pairs[0][1].claim_id == "formal_region_01_2024_initial_gdp"


def test_parse_qa_response_rejects_non_json_or_missing_answer():
    assert parse_qa_response('{"answer":"352.6094亿元","supporting_excerpt":"原文"}') == (
        "352.6094亿元",
        "原文",
    )
    assert parse_qa_response("not-json") == ("", "")
    assert parse_qa_response('{"supporting_excerpt":"原文"}') == ("", "")
