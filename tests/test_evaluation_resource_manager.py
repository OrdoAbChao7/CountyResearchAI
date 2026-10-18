from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from county_research_ai.evaluation.resource_manager import (
    ResourceDeniedError,
    ResourceExhaustedError,
    ResourceLimit,
    ResourceManager,
    ResourceRequest,
    ResourceStateError,
)


def _manager(path, capacity: int = 2) -> ResourceManager:
    return ResourceManager(
        path,
        limits={
            ("gemini", "gemini-3.1-flash-lite", "llm"): ResourceLimit(
                capacity_units=capacity,
                billing_class="free_confirmed",
            )
        },
    )


def _request(run_id: str, units: int = 1) -> ResourceRequest:
    return ResourceRequest(
        provider="gemini",
        model="gemini-3.1-flash-lite",
        kind="llm",
        units=units,
        run_id=run_id,
    )


def test_reserve_and_settle_persist_usage(tmp_path):
    manager = _manager(tmp_path / "resources.sqlite")

    lease = manager.reserve(_request("run-1"))
    manager.settle(lease.lease_id, 1, usage={"prompt_tokens": 12, "completion_tokens": 8})

    snapshot = manager.snapshot()
    assert snapshot.consumed[("gemini", "gemini-3.1-flash-lite", "llm")] == 1
    assert snapshot.active == 0
    assert snapshot.events[-1]["status"] == "settled"


def test_reservation_rejects_when_capacity_is_exhausted(tmp_path):
    manager = _manager(tmp_path / "resources.sqlite", capacity=1)

    manager.reserve(_request("run-1"))
    with pytest.raises(ResourceExhaustedError):
        manager.reserve(_request("run-2"))


def test_failed_lease_is_conservatively_counted_and_cannot_be_settled_twice(tmp_path):
    manager = _manager(tmp_path / "resources.sqlite")

    lease = manager.reserve(_request("run-1"))
    manager.fail(lease.lease_id, "timeout")

    assert manager.snapshot().consumed[("gemini", "gemini-3.1-flash-lite", "llm")] == 1
    with pytest.raises(ResourceStateError):
        manager.settle(lease.lease_id, 1)


def test_paid_or_unknown_billing_class_is_denied_by_default(tmp_path):
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={
            ("paid", "model", "llm"): ResourceLimit(2, billing_class="paid"),
            ("unknown", "model", "llm"): ResourceLimit(2, billing_class="unknown"),
        },
    )

    with pytest.raises(ResourceDeniedError):
        manager.reserve(ResourceRequest("paid", "model", "llm", 1, "run-paid"))
    with pytest.raises(ResourceDeniedError):
        manager.reserve(ResourceRequest("unknown", "model", "llm", 1, "run-unknown"))


def test_user_authorized_paid_billing_class_can_reserve_and_settle(tmp_path):
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={
            ("deepseek", "deepseek-flash", "llm"): ResourceLimit(
                2,
                billing_class="paid_authorized",
            )
        },
    )

    lease = manager.reserve(
        ResourceRequest("deepseek", "deepseek-flash", "llm", 1, "run-paid-authorized")
    )
    manager.settle(lease.lease_id, 1, usage={"total_tokens": 1})

    assert manager.snapshot().consumed[("deepseek", "deepseek-flash", "llm")] == 1


def test_two_manager_instances_reserve_atomically(tmp_path):
    db_path = tmp_path / "resources.sqlite"
    manager_a = _manager(db_path, capacity=1)
    manager_b = _manager(db_path, capacity=1)

    def reserve(manager, run_id):
        try:
            manager.reserve(_request(run_id))
            return "reserved"
        except ResourceExhaustedError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: reserve(*pair), [(manager_a, "a"), (manager_b, "b")]))

    assert sorted(results) == ["rejected", "reserved"]


def test_settlement_rejects_actual_usage_over_capacity(tmp_path):
    manager = _manager(tmp_path / "resources.sqlite", capacity=2)

    lease = manager.reserve(_request("run-1"))
    with pytest.raises(ResourceExhaustedError):
        manager.settle(lease.lease_id, 3)

    snapshot = manager.snapshot()
    assert snapshot.active == 0
    assert snapshot.consumed[("gemini", "gemini-3.1-flash-lite", "llm")] == 3
    assert snapshot.events[-1]["status"] == "overrun"


def test_overrun_usage_blocks_later_reservations(tmp_path):
    manager = _manager(tmp_path / "resources.sqlite", capacity=2)

    lease = manager.reserve(_request("run-1"))
    with pytest.raises(ResourceExhaustedError):
        manager.settle(lease.lease_id, 3)

    with pytest.raises(ResourceExhaustedError):
        manager.reserve(_request("run-2"))


def test_reopened_manager_rejects_persisted_limit_drift(tmp_path):
    db_path = tmp_path / "resources.sqlite"
    _manager(db_path, capacity=2)

    with pytest.raises(ResourceStateError, match="resource limit drift"):
        _manager(db_path, capacity=3)


def test_run_scoped_limit_rejects_one_run_without_blocking_other_runs(tmp_path):
    key = ("gemini", "gemini-3.1-flash-lite", "llm")
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={key: ResourceLimit(10)},
        run_limits={"run-1": {key: 2}},
    )

    lease = manager.reserve(_request("run-1", units=2))
    manager.settle(lease.lease_id, 2)

    with pytest.raises(ResourceExhaustedError, match="run-scoped"):
        manager.reserve(_request("run-1"))

    other_lease = manager.reserve(_request("run-2"))
    manager.settle(other_lease.lease_id, 1)
