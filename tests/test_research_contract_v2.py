from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from county_research_ai.domain.research_contracts import (
    BudgetCaps,
    DateWindow,
    ResearchContract,
    ResearchSpec,
)


def _contract(**overrides) -> ResearchContract:
    payload = {
        "objective": "评估德清县 2024 年产业发展与财政健康",
        "regions": ["德清县"],
        "required_questions": ["2024 年地区生产总值是多少？"],
    }
    payload.update(overrides)
    return ResearchContract(**payload)


def test_contract_defaults_and_json_round_trip():
    contract = _contract()

    restored = ResearchContract.model_validate_json(contract.model_dump_json())

    assert restored == contract
    assert contract.budget.max_steps == 8
    assert contract.budget.max_search_calls == 3
    assert contract.evidence_thresholds.min_supported_claims == 1
    assert contract.requested_output.format == "decision_brief"
    assert contract.domain_adapter == "county_industry"


def test_blank_objective_is_rejected():
    with pytest.raises(ValidationError, match="objective"):
        _contract(objective="   ")


def test_blank_region_is_rejected_and_duplicates_are_removed():
    with pytest.raises(ValidationError, match="regions"):
        _contract(regions=["德清县", "  "])

    contract = _contract(regions=["德清县", "德清县", "长兴县"])

    assert contract.regions == ["德清县", "长兴县"]


def test_inverted_date_window_is_rejected():
    with pytest.raises(ValidationError, match="date_window"):
        _contract(
            date_window=DateWindow(start=date(2024, 1, 1), end=date(2023, 1, 1))
        )


def test_negative_budget_caps_are_rejected():
    with pytest.raises(ValidationError):
        BudgetCaps(max_steps=0)
    with pytest.raises(ValidationError):
        BudgetCaps(max_search_calls=-1)
    with pytest.raises(ValidationError):
        BudgetCaps(deadline_seconds=-5)


def test_blank_required_question_is_rejected():
    with pytest.raises(ValidationError, match="required_questions"):
        _contract(required_questions=["有效问题", " "])


def test_contract_maps_to_research_spec_with_scope_and_budget():
    contract = _contract(
        date_window=DateWindow(start=date(2020, 1, 1), end=date(2024, 12, 31)),
        budget=BudgetCaps(max_tokens=9000, max_steps=5),
        mode="long-history",
    )

    spec = contract.to_research_spec()

    assert isinstance(spec, ResearchSpec)
    assert spec.region_name == "德清县"
    assert spec.mode == "long-history"
    assert spec.budget == 9000
    assert spec.target_years == ["2020", "2024"]
    assert spec.required_question_slots[0].time_period == "2020-01-01~2024-12-31"
    assert spec.required_question_slots[0].budget_chars == 9000


def test_research_spec_maps_back_to_contract():
    spec = ResearchSpec(
        region_id="德清县",
        region_name="德清县",
        research_focus="竹产业",
        required_question_slots=[],
        budget=15000,
    )

    contract = ResearchContract.from_research_spec(spec)

    assert contract.regions == ["德清县"]
    assert contract.objective == "竹产业"
    assert contract.budget.max_tokens == 15000


def test_date_window_contains_is_inclusive():
    window = DateWindow(start=date(2020, 1, 1), end=date(2024, 12, 31))

    assert window.contains(date(2020, 1, 1))
    assert window.contains(date(2024, 12, 31))
    assert not window.contains(date(2019, 12, 31))
    assert not window.contains(date(2025, 1, 1))
    assert not DateWindow().is_set


def test_research_spec_target_years_round_trip_to_date_window():
    spec = ResearchSpec(
        region_id="德清县",
        region_name="德清县",
        research_focus="产业",
        target_years=["2020", "2024"],
        required_question_slots=[],
        budget=8000,
    )

    contract = ResearchContract.from_research_spec(spec)

    assert contract.date_window.start == date(2020, 1, 1)
    assert contract.date_window.end == date(2024, 12, 31)
    assert contract.to_research_spec().target_years == ["2020", "2024"]
