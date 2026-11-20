from __future__ import annotations

import json

from scripts.merge_independent_observations import merge_observations


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_merge_observations_joins_judge_and_report_qa_scores(tmp_path):
    claims = tmp_path / "claims.jsonl"
    judges = tmp_path / "judges.jsonl"
    qa = tmp_path / "qa.jsonl"
    output = tmp_path / "observations.jsonl"
    _write_jsonl(
        claims,
        [
            {
                "status": "VALID",
                "run_id": "run-1",
                "group": "C",
                "region": "德清县",
                "task_id": "snapshot",
                "repeat": 1,
                "metrics": {"fact_accuracy": 1.0, "key_fact_coverage": 1.0, "evidence_support_rate": 1.0},
            }
        ],
    )
    _write_jsonl(judges, [{"status": "VALID", "run_id": "run-1", "analysis_depth": 0.8}])
    _write_jsonl(qa, [{"run_id": "run-1", "status": "VALID", "qa_accuracy": 1.0}])

    summary = merge_observations(claims, judges, qa, output)
    row = json.loads(output.read_text(encoding="utf-8"))

    assert summary["rows"] == 1
    assert row["metrics"]["analysis_depth"] == 0.8
    assert row["metrics"]["report_qa_accuracy"] == 1.0


def test_merge_observations_keeps_claim_rows_when_optional_scores_are_missing(tmp_path):
    claims = tmp_path / "claims.jsonl"
    output = tmp_path / "observations.jsonl"
    _write_jsonl(
        claims,
        [
            {
                "status": "VALID",
                "run_id": "run-1",
                "metrics": {"fact_accuracy": 0.5},
            }
        ],
    )

    merge_observations(claims, None, None, output)
    row = json.loads(output.read_text(encoding="utf-8"))

    assert row["metrics"] == {"fact_accuracy": 0.5}


def test_merge_observations_does_not_use_failed_judge_depth(tmp_path):
    claims = tmp_path / "claims.jsonl"
    judges = tmp_path / "judges.jsonl"
    output = tmp_path / "observations.jsonl"
    _write_jsonl(
        claims,
        [{"status": "VALID", "run_id": "run-1", "metrics": {"fact_accuracy": 0.5}}],
    )
    _write_jsonl(
        judges,
        [{"status": "FAILED_JUDGE", "run_id": "run-1", "analysis_depth": 0.8}],
    )

    summary = merge_observations(claims, judges, None, output)
    row = json.loads(output.read_text(encoding="utf-8"))

    assert summary["rows_with_judge"] == 0
    assert "analysis_depth" not in row["metrics"]
