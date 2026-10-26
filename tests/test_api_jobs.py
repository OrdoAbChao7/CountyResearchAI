from __future__ import annotations

import time

import pytest

from county_research_ai.api.jobs import JobStatus, JobStore
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.domain.research_contracts import ResearchContract


def _contract() -> ResearchContract:
    return ResearchContract(objective="评估德清县产业", regions=["德清县"])


def _store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "jobs.sqlite")


def test_create_get_and_list_jobs(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")

    loaded = store.get_job(job.job_id)

    assert loaded is not None
    assert loaded.status is JobStatus.QUEUED
    assert loaded.contract.objective == "评估德清县产业"
    assert loaded.county == "德清县"
    assert loaded.mode_label == "MOCK"
    assert [item.job_id for item in store.list_jobs()] == [job.job_id]
    assert [event.event_type for event in store.list_events(job.job_id)] == ["job.queued"]


def test_events_are_ordered_and_filterable(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")
    store.append_event(job.job_id, "stage.collect.started", {"x": 1})
    store.append_event(job.job_id, "stage.collect.completed", {"y": 2})

    events = store.list_events(job.job_id)
    after = store.list_events(job.job_id, after_seq=events[1].seq)

    assert [event.seq for event in events] == [1, 2, 3]
    assert [event.event_type for event in events] == [
        "job.queued",
        "stage.collect.started",
        "stage.collect.completed",
    ]
    assert [event.event_type for event in after] == ["stage.collect.completed"]


def test_cancel_requests_only_active_jobs(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")

    assert store.request_cancel(job.job_id) is True
    assert store.is_cancel_requested(job.job_id) is True

    store.mark_terminal(
        job.job_id,
        JobStatus.SUCCEEDED,
        outcome=ResearchOutcome.SUFFICIENT,
        outcome_reason="ok",
    )
    assert store.request_cancel(job.job_id) is False


def test_recover_interrupted_marks_running_jobs(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")
    store.mark_running(job.job_id)

    recovered = JobStore(tmp_path / "jobs.sqlite").recover_interrupted()
    loaded = JobStore(tmp_path / "jobs.sqlite").get_job(job.job_id)

    assert recovered == 1
    assert loaded is not None
    assert loaded.status is JobStatus.INTERRUPTED
    assert loaded.outcome is ResearchOutcome.FAILED
    assert loaded.error_code == "process_restarted"
    assert JobStore(tmp_path / "jobs.sqlite").recover_interrupted() == 0


def test_requeue_clears_previous_result(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")
    store.mark_running(job.job_id)
    store.mark_terminal(
        job.job_id,
        JobStatus.FAILED,
        outcome=ResearchOutcome.FAILED,
        error_code="Boom",
        error_message="boom",
        result={"x": 1},
    )
    store.request_cancel(job.job_id)  # terminal: ignored

    store.requeue(job.job_id)
    loaded = store.get_job(job.job_id)

    assert loaded is not None
    assert loaded.status is JobStatus.QUEUED
    assert loaded.outcome is None
    assert loaded.result == {}
    assert loaded.error_code == ""
    assert loaded.cancel_requested is False


def test_requeue_rejects_running_job(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")
    store.mark_running(job.job_id)

    with pytest.raises(ValueError, match="running"):
        store.requeue(job.job_id)


def test_mark_terminal_requires_terminal_status(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")

    with pytest.raises(ValueError, match="terminal"):
        store.mark_terminal(
            job.job_id,
            JobStatus.RUNNING,
            outcome=ResearchOutcome.SUFFICIENT,
        )


def test_unknown_job_returns_none(tmp_path):
    assert _store(tmp_path).get_job("missing") is None
    with pytest.raises(KeyError):
        _store(tmp_path).request_cancel("missing")


def test_busy_store_does_not_block_event_appends(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")
    started = time.monotonic()
    for index in range(25):
        store.append_event(job.job_id, "tick", {"index": index})

    assert time.monotonic() - started < 5
    assert len(store.list_events(job.job_id)) == 26


def test_claim_for_execution_is_atomic(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(_contract(), mode_label="MOCK")

    token = store.claim_for_execution(job.job_id, owner="worker-a", lease_seconds=60)
    assert token is not None
    assert store.claim_for_execution(job.job_id, owner="worker-b", lease_seconds=60) is None
    assert store.get_job(job.job_id).status is JobStatus.RUNNING
    assert store.get_job(job.job_id).lease_owner == "worker-a"


def test_live_lease_blocks_recovery_and_takeover(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = JobStore(path)
    job = store.create_job(_contract(), mode_label="MOCK")
    token = store.claim_for_execution(job.job_id, owner="worker-a", lease_seconds=60)

    other = JobStore(path)
    assert other.recover_interrupted() == 0
    assert other.claim_for_execution(job.job_id, owner="worker-b", lease_seconds=60) is None
    assert store.renew_lease(
        job.job_id, owner="worker-a", fencing_token=token, lease_seconds=60
    )
    assert not other.renew_lease(
        job.job_id, owner="worker-b", fencing_token=token, lease_seconds=60
    )


def test_expired_lease_takeover_rejects_stale_terminal_write(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = JobStore(path)
    job = store.create_job(_contract(), mode_label="MOCK")
    first_token = store.claim_for_execution(
        job.job_id, owner="worker-a", lease_seconds=0.1
    )
    time.sleep(0.15)

    other = JobStore(path)
    second_token = other.claim_for_execution(
        job.job_id, owner="worker-b", lease_seconds=60
    )

    assert first_token is not None
    assert second_token is not None
    assert second_token > first_token
    stale = store.finish_job(
        job.job_id,
        JobStatus.SUCCEEDED,
        outcome=ResearchOutcome.SUFFICIENT,
        event_type="job.completed",
        owner="worker-a",
        fencing_token=first_token,
    )
    assert stale is False
    assert store.get_job(job.job_id).status is JobStatus.RUNNING

    fresh = other.finish_job(
        job.job_id,
        JobStatus.SUCCEEDED,
        outcome=ResearchOutcome.SUFFICIENT,
        event_type="job.completed",
        owner="worker-b",
        fencing_token=second_token,
    )
    assert fresh is True
    loaded = store.get_job(job.job_id)
    assert loaded.status is JobStatus.SUCCEEDED
    assert loaded.lease_owner == ""
    assert store.list_events(job.job_id)[-1].event_type == "job.completed"


def test_concurrent_claims_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "jobs.sqlite"
    store = JobStore(path)
    job = store.create_job(_contract(), mode_label="MOCK")
    stores = [JobStore(path) for _ in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda index: stores[index].claim_for_execution(
                    job.job_id, owner=f"worker-{index}", lease_seconds=60
                ),
                range(8),
            )
        )

    assert sum(result is not None for result in results) == 1
    assert store.get_job(job.job_id).status is JobStatus.RUNNING
