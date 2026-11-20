from __future__ import annotations

from scripts.validate_quality_dataset import (
    GROUND_TRUTH,
    load_blind,
    validate_fact,
)

from county_research_ai.evaluation.ground_truth import GroundTruthStore


def test_blind_pilot_facts_validate_and_are_disjoint_from_dev():
    blind = load_blind()

    assert len({fact["task_id"] for fact in blind}) == 2
    results = [validate_fact(fact) for fact in blind]
    assert all(result["ok"] for result in results)
    assert all(result["snapshot_sha256"] for result in results)
    assert all(result["quote_sha256"] for result in results)

    dev_keys = {
        (claim.region, claim.research_mode)
        for claim in GroundTruthStore.load(GROUND_TRUTH)
    }
    blind_keys = {(fact["region"], fact["mode"]) for fact in blind}
    assert dev_keys.isdisjoint(blind_keys)


def test_tampered_or_ambiguous_quote_fails_validation():
    fact = dict(load_blind()[0])
    fact["quote"] = "这是一段被篡改的引文"

    result = validate_fact(fact)

    assert result["ok"] is False
    assert "quote_not_in_snapshot" in result["errors"]
