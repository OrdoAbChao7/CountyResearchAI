from __future__ import annotations

from pathlib import Path

from scripts.run_continuation_experiment import (
    build_continuation_specs,
    validate_continuation_benchmark,
)


def test_continuation_benchmark_hash_and_task_quotas_are_frozen():
    result = validate_continuation_benchmark()

    assert result["claim_count"] == 90
    assert result["source_hash"] == (
        "a5fa504976b83c57334f36cc246ef2a3f73b706957a4c9a2725d222d0f4f1bdd"
    )
    assert result["regions"] == 6
    assert result["modes"] == {"snapshot": 30, "rise-fall": 30, "long-history": 30}
    assert result["claims_per_region_mode"] == 5


def test_stage_a_specs_match_regions_modes_and_groups():
    specs = build_continuation_specs(
        model="gemini-3.1-flash-lite",
        search_provider="tavily",
        batch_id="continuation_stage_a_test",
        region_names=["德清县", "长汀县"],
    )

    assert len(specs) == 18
    assert {spec.county for spec in specs} == {"德清县", "长汀县"}
    assert {spec.mode for spec in specs} == {"snapshot", "rise-fall", "long-history"}
    assert {spec.group for spec in specs} == {"A", "B", "C"}
    assert all(spec.config["execution_policy"] == "natural" for spec in specs)
    assert all(spec.config["formal_target"] is True for spec in specs)
    assert all(spec.config["ground_truth_claim_quota"] == 5 for spec in specs)


def test_continuation_runner_paths_are_inside_project():
    from scripts import run_continuation_experiment

    assert Path(run_continuation_experiment.CONTINUATION_ROOT).name == "independent_comparison"
