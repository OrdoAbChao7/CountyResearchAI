"""Two-process lease/fencing stress test.

Covers simultaneous claims, lease expiry takeover, stale worker writes, worker
exit without finishing, recovery, and one successful terminal write per job.
No provider calls.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from county_research_ai.api.jobs import JobStatus, JobStore
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.domain.research_contracts import ResearchContract

OUTPUT = Path("experiments/quality/20261026_q7_stress")


def _contract() -> ResearchContract:
    return ResearchContract(objective="lease stress", regions=["德清县"])


def _worker(
    db_path: str,
    job_ids: list[str],
    owner: str,
    lease_seconds: float,
    barrier,
    queue,
    crash_job: str,
) -> None:
    store = JobStore(db_path)
    rng = random.Random(hash(owner) & 0xFFFF)
    barrier.wait()
    expiry_job = "lease-expiry-job"
    if owner == "worker-a":
        token = store.claim_for_execution(
            expiry_job, owner=owner, lease_seconds=lease_seconds
        )
        if token is not None:
            queue.put(
                {"event": "claimed", "job_id": expiry_job, "owner": owner, "token": token}
            )
            time.sleep(lease_seconds + 0.8)
            finished = store.finish_job(
                expiry_job,
                JobStatus.SUCCEEDED,
                outcome=ResearchOutcome.SUFFICIENT,
                event_type="job.completed",
                outcome_reason="stale_attempt",
                owner=owner,
                fencing_token=token,
            )
            queue.put(
                {
                    "event": "stale_finish",
                    "job_id": expiry_job,
                    "owner": owner,
                    "accepted": bool(finished),
                }
            )
        token = store.claim_for_execution(
            crash_job, owner=owner, lease_seconds=lease_seconds
        )
        if token is not None:
            queue.put(
                {"event": "claimed", "job_id": crash_job, "owner": owner, "token": token}
            )
            queue.put({"event": "crash", "job_id": crash_job, "owner": owner})
            return
    else:
        time.sleep(lease_seconds + 0.9)
        for special in (expiry_job, crash_job):
            token = store.claim_for_execution(
                special, owner=owner, lease_seconds=lease_seconds
            )
            if token is None:
                continue
            queue.put(
                {"event": "claimed", "job_id": special, "owner": owner, "token": token}
            )
            finished = store.finish_job(
                special,
                JobStatus.SUCCEEDED,
                outcome=ResearchOutcome.SUFFICIENT,
                event_type="job.completed",
                outcome_reason="takeover",
                owner=owner,
                fencing_token=token,
            )
            queue.put(
                {
                    "event": "finished",
                    "job_id": special,
                    "owner": owner,
                    "token": token,
                    "accepted": bool(finished),
                }
            )
    normal_jobs = [job for job in job_ids if job not in {expiry_job, crash_job}]
    for round_number in range(6):
        for job_id in rng.sample(normal_jobs, len(normal_jobs)):
            token = store.claim_for_execution(
                job_id, owner=owner, lease_seconds=lease_seconds
            )
            if token is None:
                continue
            queue.put(
                {
                    "event": "claimed",
                    "job_id": job_id,
                    "owner": owner,
                    "token": token,
                    "round": round_number,
                }
            )
            time.sleep(0.05 + rng.random() * 0.1)
            renewed = store.renew_lease(
                job_id,
                owner=owner,
                fencing_token=token,
                lease_seconds=lease_seconds,
            )
            finished = store.finish_job(
                job_id,
                JobStatus.SUCCEEDED,
                outcome=ResearchOutcome.SUFFICIENT,
                event_type="job.completed",
                outcome_reason="stress",
                owner=owner,
                fencing_token=token,
            )
            queue.put(
                {
                    "event": "finished",
                    "job_id": job_id,
                    "owner": owner,
                    "token": token,
                    "renewed": renewed,
                    "accepted": bool(finished),
                }
            )
            if not finished:
                continue


def _recovery(db_path: str, queue) -> None:
    store = JobStore(db_path)
    recovered = store.recover_interrupted()
    queue.put({"event": "recovered", "count": recovered})
    for job in store.list_jobs(limit=100):
        if job.status not in {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.INTERRUPTED,
        }:
            continue
        token = store.claim_for_execution(
            job.job_id, owner="recovery-worker", lease_seconds=2.0
        )
        if token is None:
            continue
        finished = store.finish_job(
            job.job_id,
            JobStatus.SUCCEEDED,
            outcome=ResearchOutcome.SUFFICIENT,
            event_type="job.completed",
            outcome_reason="recovery",
            owner="recovery-worker",
            fencing_token=token,
        )
        queue.put(
            {
                "event": "finished",
                "job_id": job.job_id,
                "owner": "recovery-worker",
                "token": token,
                "accepted": bool(finished),
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lease-seconds", type=float, default=0.45)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    db_path = args.output / "stress_jobs.sqlite"
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()
    store = JobStore(db_path)
    job_ids = []
    for index in range(4):
        job = store.create_job(_contract(), mode_label="MOCK", job_id=f"normal-{index}")
        job_ids.append(job.job_id)
    expire_job = store.create_job(
        _contract(), mode_label="MOCK", job_id="lease-expiry-job"
    ).job_id
    crash_job = store.create_job(
        _contract(), mode_label="MOCK", job_id="crash-job"
    ).job_id
    job_ids.extend([expire_job, crash_job])

    context = mp.get_context("spawn")
    barrier = context.Barrier(args.workers)
    queue = context.Queue()
    owners = ["worker-a", "worker-b"][: args.workers]
    processes = [
        context.Process(
            target=_worker,
            args=(str(db_path), job_ids, owner, args.lease_seconds, barrier, queue, crash_job),
        )
        for owner in owners
    ]
    started = time.monotonic()
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    recovery = context.Process(target=_recovery, args=(str(db_path), queue))
    recovery.start()
    recovery.join(timeout=30)

    events = []
    while not queue.empty():
        events.append(queue.get())
    final = {job.job_id: store.get_job(job.job_id) for job in store.list_jobs(limit=100)}
    claims = Counter(event["job_id"] for event in events if event["event"] == "claimed")
    finished = [
        event for event in events if event["event"] == "finished" and event["accepted"]
    ]
    finished_per_job = Counter(event["job_id"] for event in finished)
    stale = [
        event
        for event in events
        if event["event"] == "stale_finish"
    ]
    crashes = [event for event in events if event["event"] == "crash"]
    recovered = [event for event in events if event["event"] == "recovered"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "TWO_PROCESS_LEASE_STRESS",
        "workers": args.workers,
        "jobs": len(job_ids),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "all_terminal": all(job is not None and job.status.terminal for job in final.values()),
        "statuses": {job_id: (job.status.value if job else "MISSING") for job_id, job in final.items()},
        "claims_per_job": dict(sorted(claims.items())),
        "successful_terminal_writes": dict(sorted(finished_per_job.items())),
        "exactly_one_success_per_job": all(
            finished_per_job.get(job_id, 0) == 1 for job_id in job_ids
        ),
        "stale_finish_attempts": stale,
        "stale_rejected": all(not event["accepted"] for event in stale),
        "crash_events": crashes,
        "recovery_events": recovered,
        "takeovers": sorted(
            job_id for job_id, count in claims.items() if count > 1
        ),
        "event_count": len(events),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "events.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    ok = (
        summary["all_terminal"]
        and summary["exactly_one_success_per_job"]
        and summary["stale_rejected"]
        and bool(stale)
        and bool(summary["takeovers"])
        and bool(summary["crash_events"])
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
