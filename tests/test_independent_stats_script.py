from __future__ import annotations

import json

from scripts.generate_independent_stats import generate_stats


def _row(run_id: str, group: str, value: float) -> dict:
    return {
        "run_id": run_id,
        "group": group,
        "region": "甲县",
        "task_id": "snapshot",
        "repeat": 1,
        "status": "VALID",
        "metrics": {
            "fact_accuracy": value,
            "key_fact_coverage": value,
            "evidence_support_rate": value,
            "total_ground_truth_claims": 1,
            "verifiable_claims": 1,
            "unverified_claims": 0,
            "supported_claims": 1,
            "error_rate": 1 - value,
            "analysis_depth": value,
            "report_qa_accuracy": value,
        },
        "duration_seconds": 10.0,
        "resource_usage": {"gemini:model:llm": 1000, "tavily:search:search": 2},
    }


def test_stats_script_generates_summary_pairs_and_svg_from_valid_rows(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in [_row("a-1", "A", 0.4), _row("c-1", "C", 0.8)]
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_stats(
        source,
        summary_csv=tmp_path / "summary.csv",
        paired_csv=tmp_path / "paired.csv",
        summary_json=tmp_path / "summary.json",
        figures_dir=tmp_path / "figures",
    )

    assert result["status"] == "OK"
    assert "fact_accuracy" in (tmp_path / "summary.csv").read_text(encoding="utf-8")
    assert "C" in (tmp_path / "paired.csv").read_text(encoding="utf-8")
    assert "甲县" in (tmp_path / "region_summary.csv").read_text(encoding="utf-8")
    assert (tmp_path / "figures" / "fact_accuracy.svg").is_file()
    assert (tmp_path / "figures" / "region_fact_accuracy.svg").is_file()
    assert (tmp_path / "figures" / "analysis_depth.svg").is_file()
    assert (tmp_path / "figures" / "llm_tokens.svg").is_file()


def test_stats_script_does_not_fabricate_figures_without_valid_rows(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(
        json.dumps({"run_id": "blocked", "status": "BLOCKED"}) + "\n",
        encoding="utf-8",
    )

    result = generate_stats(
        source,
        summary_csv=tmp_path / "summary.csv",
        paired_csv=tmp_path / "paired.csv",
        summary_json=tmp_path / "summary.json",
        figures_dir=tmp_path / "figures",
    )

    assert result["status"] == "NO_VALID_METRICS"
    assert not (tmp_path / "figures" / "fact_accuracy.svg").exists()
