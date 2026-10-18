from __future__ import annotations

from pathlib import Path

from scripts.audit_continuation_experiment import audit_batch


def test_stage_a_audit_preserves_failure_and_closes_resource_ledger():
    root = (
        Path(__file__).parents[1]
        / "experiments"
        / "independent_comparison"
        / "runs"
        / "continuation_natural_stage_a_20261019"
    )

    result = audit_batch(root)

    assert result["source_hash_verified"] is True
    assert result["benchmark"]["claim_count"] == 90
    assert result["summary_status"] == "STOPPED"
    assert result["statuses"] == {"FAILED": 1}
    assert len(result["failed_runs"]) == 1
    assert result["resource"]["status"] == "CLOSED"
    assert result["resource"]["active_leases"] == 0
