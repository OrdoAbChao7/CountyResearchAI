from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from county_research_ai.api.app import create_app
from county_research_ai.api.jobs import JobRecord, JobStatus, JobStore
from county_research_ai.api.worker import JobRunner
from county_research_ai.config import Settings
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.domain.research_contracts import ResearchContract


class FakeRunner:
    mode_label = "MOCK"

    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)

    def shutdown(self, *, wait: bool = False) -> None:
        _ = wait


def _contract_payload() -> dict:
    return {
        "contract": {
            "objective": "评估德清县 2024 年产业与财政",
            "regions": ["德清县"],
            "required_questions": ["2024 年地区生产总值是多少？"],
            "budget": {"max_steps": 5, "max_search_calls": 2},
        }
    }


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    data_dir = tmp_path / "data"
    reports_dir = tmp_path / "reports"
    return settings.model_copy(
        update={
            "storage": settings.storage.model_copy(
                update={"data_dir": str(data_dir), "reports_dir": str(reports_dir)}
            ),
            "data_dir": data_dir,
            "reports_dir": reports_dir,
            "llm": settings.llm.model_copy(update={"api_key": SecretStr("")}),
            "search": settings.search.model_copy(update={"api_key": SecretStr("")}),
        }
    )


def _client(tmp_path: Path) -> tuple[TestClient, JobStore, FakeRunner]:
    store = JobStore(tmp_path / "jobs.sqlite")
    runner = FakeRunner()
    app = create_app(
        settings=_settings(tmp_path),
        store=store,
        runner=runner,  # type: ignore[arg-type]
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    return TestClient(app), store, runner


def test_health_and_capabilities(tmp_path):
    client, _, _ = _client(tmp_path)

    with client:
        health = client.get("/health")
        capabilities = client.get("/api/v1/capabilities")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["mode_label"] == "MOCK"
    assert body["live_enabled"] is False
    assert body["enforced_caps"] == ["deadline_seconds"]
    assert body["bounded_per_call_caps"] == ["max_tokens", "max_documents"]
    assert "max_cost" in body["unenforced_caps"]


def test_create_list_get_and_cancel(tmp_path):
    client, _, runner = _client(tmp_path)

    with client:
        created = client.post("/api/v1/research/tasks", json=_contract_payload())
        job = created.json()
        listed = client.get("/api/v1/research/tasks").json()
        detail = client.get(f"/api/v1/research/tasks/{job['job_id']}").json()
        cancelled = client.post(f"/api/v1/research/tasks/{job['job_id']}/cancel")
        again = client.post(f"/api/v1/research/tasks/{job['job_id']}/cancel")

    assert created.status_code == 202
    assert job["status"] == "QUEUED"
    assert job["contract"]["objective"] == "评估德清县 2024 年产业与财政"
    assert runner.submitted == [job["job_id"]]
    assert [item["job_id"] for item in listed] == [job["job_id"]]
    assert detail["status"] == "QUEUED"
    assert cancelled.status_code == 200
    assert cancelled.json()["cancel_requested"] is True
    assert again.status_code == 200


def test_resume_requeues_and_resubmits(tmp_path):
    client, store, runner = _client(tmp_path)

    with client:
        job = client.post("/api/v1/research/tasks", json=_contract_payload()).json()
        store.mark_running(job["job_id"])
        store.mark_terminal(
            job["job_id"],
            JobStatus.INTERRUPTED,
            outcome=ResearchOutcome.FAILED,
            error_code="process_restarted",
        )
        resumed = client.post(f"/api/v1/research/tasks/{job['job_id']}/resume")

    assert resumed.status_code == 202
    assert resumed.json()["status"] == "QUEUED"
    assert runner.submitted.count(job["job_id"]) == 2


def test_resume_rejects_succeeded_job(tmp_path):
    client, store, _ = _client(tmp_path)

    with client:
        job = client.post("/api/v1/research/tasks", json=_contract_payload()).json()
        store.mark_terminal(
            job["job_id"],
            JobStatus.SUCCEEDED,
            outcome=ResearchOutcome.SUFFICIENT,
        )
        response = client.post(f"/api/v1/research/tasks/{job['job_id']}/resume")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_already_succeeded"


def test_validation_and_not_found_have_consistent_error_shape(tmp_path):
    client, _, _ = _client(tmp_path)

    with client:
        invalid = client.post(
            "/api/v1/research/tasks",
            json={"contract": {"objective": " ", "regions": []}},
        )
        missing = client.get("/api/v1/research/tasks/does-not-exist")
        bad_id = client.get("/api/v1/research/tasks/bad%20id")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"
    assert bad_id.status_code == 400
    assert bad_id.json()["error"]["code"] == "invalid_id"


def test_events_and_sse_stream_for_terminal_job(tmp_path):
    client, store, _ = _client(tmp_path)
    with client:
        job = client.post("/api/v1/research/tasks", json=_contract_payload()).json()
        store.append_event(job["job_id"], "job.completed", {"outcome": "SUFFICIENT"})
        store.mark_terminal(
            job["job_id"],
            JobStatus.SUCCEEDED,
            outcome=ResearchOutcome.SUFFICIENT,
        )
        events = client.get(f"/api/v1/research/tasks/{job['job_id']}/events").json()
        stream = client.get(f"/api/v1/research/tasks/{job['job_id']}/stream")

    assert [event["event_type"] for event in events][-2:] == [
        "job.queued",
        "job.completed",
    ]
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "event: job.completed" in stream.text


def test_brief_is_rendered_with_explicit_mode(tmp_path):
    client, _, _ = _client(tmp_path)
    with client:
        job = client.post("/api/v1/research/tasks", json=_contract_payload()).json()
        brief = client.get(f"/api/v1/research/tasks/{job['job_id']}/brief")

    assert brief.status_code == 200
    assert "决策简报" in brief.text
    assert "MOCK" in brief.text
    assert "未生成可采信结论" in brief.text
    assert "attachment" in brief.headers["content-disposition"]


def test_mock_pipeline_end_to_end(tmp_path):
    app = create_app(
        settings=_settings(tmp_path),
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/research/tasks", json=_contract_payload())
        assert created.status_code == 202
        job_id = created.json()["job_id"]

        detail = {}
        for _ in range(400):
            detail = client.get(f"/api/v1/research/tasks/{job_id}").json()
            if detail["status"] in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "BUDGET_EXHAUSTED",
                "INTERRUPTED",
            }:
                break
            time.sleep(0.05)

        assert detail["status"] == "SUCCEEDED", detail
        assert detail["mode_label"] == "MOCK"
        assert detail["outcome"] in {"SUFFICIENT", "NEEDS_HUMAN_REVIEW", "NO_PROGRESS"}

        events = client.get(f"/api/v1/research/tasks/{job_id}/events").json()
        assert events[-1]["event_type"] == "job.completed"
        assert {event["event_type"] for event in events} >= {
            "stage.collect.completed",
            "stage.evidence.completed",
            "evidence.persisted",
            "stage.report.completed",
        }

        findings = client.get(f"/api/v1/research/tasks/{job_id}/findings")
        sources = client.get(f"/api/v1/research/tasks/{job_id}/sources")
        brief = client.get(f"/api/v1/research/tasks/{job_id}/brief")

    assert findings.status_code == 200
    assert isinstance(findings.json(), list)
    assert sources.status_code == 200
    assert len(sources.json()) >= 1
    assert brief.status_code == 200
    assert "MOCK" in brief.text


def _deep_contract_payload() -> dict:
    payload = _contract_payload()
    payload["contract"]["research_focus"] = "竹产业"
    payload["contract"]["options"] = {"deep_research": True}
    return payload


def _wait_for_terminal(client: TestClient, job_id: str) -> dict:
    terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "INTERRUPTED"}
    detail: dict = {}
    for _ in range(400):
        detail = client.get(f"/api/v1/research/tasks/{job_id}").json()
        if detail["status"] in terminal:
            return detail
        time.sleep(0.05)
    return detail


def test_deadline_exhaustion_is_not_reported_as_sufficient(tmp_path):
    app = create_app(
        settings=_settings(tmp_path),
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    payload = _contract_payload()
    payload["contract"]["budget"]["deadline_seconds"] = 0.000001
    with TestClient(app) as client:
        job_id = client.post("/api/v1/research/tasks", json=payload).json()["job_id"]
        detail = _wait_for_terminal(client, job_id)
        brief = client.get(f"/api/v1/research/tasks/{job_id}/brief").text

    assert detail["status"] == "BUDGET_EXHAUSTED"
    assert detail["outcome"] == "BUDGET_EXHAUSTED"
    assert detail["outcome"] != "SUFFICIENT"
    assert "BUDGET_EXHAUSTED" in brief


def test_deep_mock_pipeline_emits_fine_grained_events(tmp_path):
    app = create_app(
        settings=_settings(tmp_path),
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    with TestClient(app) as client:
        created = client.post("/api/v1/research/tasks", json=_deep_contract_payload())
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        detail = _wait_for_terminal(client, job_id)
        events = client.get(f"/api/v1/research/tasks/{job_id}/events").json()

    assert detail["status"] == "SUCCEEDED", detail
    assert detail["result"]["deep_research"]["enabled"] is True
    assert detail["result"]["deep_research"]["question_tree"]["questions"]
    types = [event["event_type"] for event in events]
    assert types[-1] == "job.completed"
    assert types.index("question_tree.created") < types.index("evidence.ingested")
    assert types.index("evidence.ingested") < types.index("conflicts.detected")
    assert types.index("conflicts.detected") < types.index("synthesis.completed")
    assert types.index("synthesis.completed") < types.index("report.rendered")
    assert {
        "retrieval.round.completed",
        "question_tree.coverage",
        "gaps.detected",
        "agent.started",
        "agent.completed",
        "synthesis.started",
        "synthesis.completed",
        "report.rendered",
    } <= set(types)
    coverage = next(
        event for event in events if event["event_type"] == "question_tree.coverage"
    )
    assert 0.0 <= coverage["payload"]["coverage_rate"] <= 1.0


def test_cancel_requested_before_execution_stops_job(tmp_path):
    settings = _settings(tmp_path)
    store = JobStore(tmp_path / "jobs.sqlite")
    runner = JobRunner(
        store,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
        settings=settings,
        live_enabled=False,
    )
    job = store.create_job(
        ResearchContract(objective="取消测试", regions=["德清县"]), mode_label="MOCK"
    )
    assert store.request_cancel(job.job_id) is True

    runner.execute(job.job_id)
    loaded = store.get_job(job.job_id)
    runner.shutdown()

    assert loaded is not None
    assert loaded.status is JobStatus.CANCELLED
    assert loaded.outcome is ResearchOutcome.CANCELLED
    assert store.list_events(job.job_id)[-1].event_type == "job.cancelled"


def test_outcome_never_sufficient_without_supported_claims():
    now = datetime.now(timezone.utc)
    contract = ResearchContract(
        objective="零支持不能算充分",
        regions=["德清县"],
        evidence_thresholds={"min_supported_claims": 0, "min_supported_ratio": 0},
    )
    job = JobRecord(
        job_id="job-zero-support",
        status=JobStatus.RUNNING,
        contract=contract,
        created_at=now,
        updated_at=now,
    )

    outcome, reason = JobRunner._outcome(
        job,
        {
            "claims": 5,
            "supported_claims": 0,
            "independent_sources": 3,
            "supported_ratio": 0.0,
            "status_counts": {"NOT_COMPARABLE": 5},
        },
    )

    assert outcome is ResearchOutcome.NO_PROGRESS
    assert reason == "no_supported_claims"


def test_startup_resubmits_queued_jobs(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.create_job(
        ResearchContract(objective="排队恢复", regions=["德清县"]), mode_label="MOCK"
    )
    runner = FakeRunner()
    app = create_app(
        settings=_settings(tmp_path),
        store=store,
        runner=runner,  # type: ignore[arg-type]
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )

    with TestClient(app):
        pass

    assert job.job_id in runner.submitted


def test_jobs_do_not_overwrite_each_others_reports(tmp_path):
    app = create_app(
        settings=_settings(tmp_path),
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    details = []
    with TestClient(app) as client:
        for objective in ("并发任务一", "并发任务二"):
            payload = _contract_payload()
            payload["contract"]["objective"] = objective
            job_id = client.post("/api/v1/research/tasks", json=payload).json()["job_id"]
            details.append(_wait_for_terminal(client, job_id))

    paths = [detail["report_path"] for detail in details]
    assert all(detail["status"] == "SUCCEEDED" for detail in details)
    assert len(set(paths)) == 2
    assert all(Path(path).is_file() for path in paths)
