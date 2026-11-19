from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from county_research_ai.api.app import create_app
from county_research_ai.api.jobs import JobStatus, JobStore
from county_research_ai.config import Settings
from county_research_ai.domain.outcomes import ResearchOutcome
from county_research_ai.domain.research_contracts import ResearchContract
from tests.projection_helpers import (
    RUN_ID,
    deep_result,
    make_claim,
    make_item,
    make_source,
    seed_graph,
)


class FakeRunner:
    mode_label = "MOCK"

    def submit(self, job_id: str) -> None:
        _ = job_id

    def shutdown(self, *, wait: bool = False) -> None:
        _ = wait


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


def _seed_api_fixture(tmp_path: Path) -> JobStore:
    supported_source = make_source(
        "snap-supported",
        url="https://example.gov.cn/supported",
        content="安吉县2024年竹产业产值为120亿元。",
    )
    missing_source = make_source(
        "snap-missing",
        url="https://example.gov.cn/missing",
        content="安吉县2024年竹林面积为80万亩。",
    )
    supported = make_claim(
        "claim-supported",
        source_id="snap-supported",
        value="120",
    )
    missing = make_claim(
        "claim-missing",
        source_id="snap-missing",
        value="999",
        metric="竹加工产值",
        statement="安吉县2024年竹加工产值为999亿元",
    )
    graph = seed_graph(
        tmp_path / "evidence.sqlite",
        RUN_ID,
        sources=[supported_source, missing_source],
        claims=[supported, missing],
    )

    other_source = make_source(
        "snap-other",
        url="https://example.gov.cn/other",
        content="安吉县2024年竹产业产值为120亿元。",
    )
    other_claim = make_claim("claim-other-run", source_id="snap-other", value="120")
    seed_graph(
        tmp_path / "evidence.sqlite",
        "other-run",
        sources=[other_source],
        claims=[other_claim],
    )

    result = deep_result(
        questions=[
            {
                "id": "q-output",
                "title": "竹产业产值是多少？",
                "category": "产业",
                "evidence_ids": ["item-supported"],
                "is_satisfied": True,
            }
        ],
        items=[make_item("item-supported", supported, supported_source)],
        gaps=[
            {
                "question_id": "q-output",
                "missing_aspect": "竹加工产值",
                "description": "缺少竹加工产值的直接来源",
                "severity": "high",
            }
        ],
        conflicts=[],
        coverage_rate=1.0,
    )
    result["report"] = {
        "provenance": "native_sections",
        "sections": [
            {
                "title": "产业现状",
                "order": 1,
                "content": "安吉县竹产业进入集群发展阶段。",
                "sources": [],
            }
        ],
        "markdown_chars": 42,
    }

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    draft = reports_dir / f"{RUN_ID}.md"
    draft.write_text("# 旧版叙述\n\n竹产业背景材料。\n", encoding="utf-8")

    store = JobStore(tmp_path / "jobs.sqlite")
    contract = ResearchContract(
        objective="分析安吉县竹产业",
        regions=["安吉县"],
        research_focus="竹产业",
        mode="snapshot",
    )
    job = store.create_job(contract, mode_label="MOCK", job_id=RUN_ID)
    store.mark_running(job.job_id)
    store.finish_job(
        job.job_id,
        JobStatus.SUCCEEDED,
        outcome=ResearchOutcome.SUFFICIENT,
        outcome_reason="thresholds_met",
        event_type="job.completed",
        report_path=str(draft),
        result=result,
    )

    shallow = store.create_job(contract, mode_label="MOCK", job_id="run-shallow")
    store.mark_running(shallow.job_id)
    store.finish_job(
        shallow.job_id,
        JobStatus.SUCCEEDED,
        outcome=ResearchOutcome.NO_PROGRESS,
        outcome_reason="no_supported_claims",
        event_type="job.completed",
        result={},
    )
    _ = graph
    return store


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=_settings(tmp_path),
        store=_seed_api_fixture(tmp_path),
        runner=FakeRunner(),  # type: ignore[arg-type]
        live_enabled=False,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        evidence_db_path=tmp_path / "evidence.sqlite",
    )
    return TestClient(app)


def test_projection_endpoints_return_typed_views(tmp_path):
    with _client(tmp_path) as client:
        questions = client.get(f"/api/v1/research/tasks/{RUN_ID}/questions")
        graph = client.get(
            f"/api/v1/research/tasks/{RUN_ID}/graph",
            params={"include_sources": "false"},
        )
        evidence = client.get(
            f"/api/v1/research/tasks/{RUN_ID}/evidence",
            params={"status": "supported"},
        )
        report = client.get(f"/api/v1/research/tasks/{RUN_ID}/report.json")
        markdown = client.get(f"/api/v1/research/tasks/{RUN_ID}/report")
        draft = client.get(f"/api/v1/research/tasks/{RUN_ID}/report/draft")

    assert questions.status_code == 200
    assert questions.json()["coverage_rate"] == 1.0
    assert questions.json()["questions"][0]["id"] == "q-output"

    assert graph.status_code == 200
    graph_body = graph.json()
    assert graph_body["meta"]["counts"]["source"] == 2
    assert graph_body["meta"]["returned_counts"].get("source", 0) == 0
    assert any(node["type"] == "county" for node in graph_body["nodes"])

    assert evidence.status_code == 200
    assert evidence.json()["total"] == 1
    assert evidence.json()["items"][0]["claim_id"] == "claim-supported"

    assert report.status_code == 200
    report_body = report.json()
    assert report_body["provenance"] == "verified_structured_facts"
    assert report_body["narrative"]["provenance"] == "native_sections"
    assert report_body["narrative"]["sections"][0]["title"] == "产业现状"
    assert report_body["citations"][0]["claim_id"] == "claim-supported"

    assert markdown.status_code == 200
    assert markdown.text.startswith("# 安吉县竹产业研究报告")
    assert "120亿元" in markdown.text
    assert "999" not in markdown.text

    assert draft.status_code == 200
    assert "旧版叙述" in draft.text
    assert "attachment" in draft.headers["content-disposition"]


def test_projection_endpoints_reject_runs_without_deep_artifacts(tmp_path):
    with _client(tmp_path) as client:
        questions = client.get("/api/v1/research/tasks/run-shallow/questions")
        graph = client.get("/api/v1/research/tasks/run-shallow/graph")

    assert questions.status_code == 409
    assert questions.json()["error"]["code"] == "artifacts_unavailable"
    assert questions.json()["error"]["reason"] == "deep_research_disabled"
    assert graph.status_code == 409


def test_claim_lookup_is_scoped_to_the_requested_run(tmp_path):
    with _client(tmp_path) as client:
        response = client.get(
            f"/api/v1/research/tasks/{RUN_ID}/claims/claim-other-run"
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "claim_not_found"


def test_report_draft_is_404_when_no_legacy_file_exists(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/v1/research/tasks/run-shallow/report/draft")
        report = client.get("/api/v1/research/tasks/run-shallow/report")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "report_not_ready"
    assert report.status_code == 200
    assert "没有通过确定性校验" in report.text
