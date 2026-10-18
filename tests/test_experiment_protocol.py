from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
PROTOCOL = ROOT / "experiments" / "independent_comparison" / "protocol"


def test_protocol_keeps_real_experiment_and_mock_policy_explicit():
    protocol = yaml.safe_load((PROTOCOL / "protocol.yaml").read_text(encoding="utf-8"))

    assert protocol["research_boundary"]["mock_results_as_real"] is False
    assert protocol["free_resource_policy"]["deepseek_search_fetch"] == "disabled_by_policy"
    assert protocol["free_resource_policy"]["gemini_billing_class"] == "unknown_until_account_level_check"
    assert protocol["budgets"]["smoke_test"]["repeats_per_group"] == 1


def test_rubric_has_required_blind_judge_dimensions():
    rubric = yaml.safe_load((PROTOCOL / "rubric.yaml").read_text(encoding="utf-8"))

    assert rubric["status"] == "FROZEN"
    dimensions = rubric["dimensions"]
    for name in (
        "factual_accuracy",
        "key_fact_coverage",
        "source_reliability",
        "causal_analysis",
        "risk_analysis",
        "unsupported_inference",
    ):
        assert name in dimensions
    assert rubric["judge_policy"]["minimum_independent_judges"] >= 2


def test_candidate_regions_exclude_development_cases_and_are_not_frozen_yet():
    regions = yaml.safe_load(
        (ROOT / "experiments" / "independent_comparison" / "datasets" / "official_regions.yaml")
        .read_text(encoding="utf-8")
    )

    assert regions["status"] == "UNFROZEN"
    names = {item["name"] for item in regions["regions"]}
    assert len(names) >= 6
    assert not names.intersection(set(regions["exclude_development_cases"]))
