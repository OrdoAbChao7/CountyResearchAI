"""FastAPI 入口测试：异步研究、SSE、证据、图谱、报告与仿真。"""
from __future__ import annotations

import time

import pytest

_TERMINAL = {"completed", "failed", "cancelled"}


def _wait_for_run(client, run_id: str, *, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/research/runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in _TERMINAL:
            return body
        time.sleep(0.2)
    raise AssertionError(f"run did not finish in {timeout}s: {run_id}")


def _start_run(client) -> dict:
    response = client.post(
        "/api/research/runs",
        json={"county": "安吉县", "focus": "竹产业"},
    )
    assert response.status_code == 202, response.text
    return response.json()


class TestSystemEndpoints:
    def test_healthz_reports_backends(self, api_client):
        response = api_client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checkpoint_backend"] in {"sqlite", "memory"}
        assert body["graph_backend"] == "memory"
        assert body["llm"]
        assert body["search"]

    def test_root_lists_api_surface(self, api_client):
        response = api_client.get("/")
        assert response.status_code == 200
        body = response.json()
        assert "POST /api/research/runs" in body["api"]
        assert body["docs"] == "/docs"

    def test_agent_catalog(self, api_client):
        response = api_client.get("/api/research/agents")
        assert response.status_code == 200
        catalog = response.json()
        assert len(catalog) == 8
        assert {item["kind"] for item in catalog} >= {"industry", "macro", "policy"}
        assert all(item["tools"] for item in catalog)


class TestResearchFlow:
    def test_create_run_and_read_all_artifacts(self, api_client):
        created = _start_run(api_client)
        run_id = created["run_id"]
        assert created["checkpoint_thread"] == run_id

        record = _wait_for_run(api_client, run_id)
        assert record["status"] == "completed", record.get("error")
        assert record["report_path"]
        assert record["evidence_count"] >= 1
        assert len(record["agent_results"]) >= 5
        assert record["plan"]
        assert record["critique"]

        report = api_client.get(f"/api/research/runs/{run_id}/report")
        assert report.status_code == 200
        assert "执行摘要" in report.json()["markdown"]

        download = api_client.get(f"/api/reports/{run_id}/download")
        assert download.status_code == 200
        assert "text/markdown" in download.headers["content-type"]
        assert "执行摘要" in download.text

        evidence = api_client.get(f"/api/evidence/runs/{run_id}")
        assert evidence.status_code == 200
        body = evidence.json()
        assert body["count"] >= 1
        evidence_id = body["items"][0]["id"]
        single = api_client.get(f"/api/evidence/runs/{run_id}/{evidence_id}")
        assert single.status_code == 200
        assert single.json()["id"] == evidence_id

        reports = api_client.get("/api/reports")
        assert reports.status_code == 200
        assert run_id in {item["run_id"] for item in reports.json()}

        runs = api_client.get("/api/research/runs")
        assert runs.status_code == 200
        assert run_id in {item["run_id"] for item in runs.json()}

        county_graph = api_client.get("/api/graph/安吉县")
        assert county_graph.status_code == 200
        graph_body = county_graph.json()
        assert graph_body["entities"]
        entity_id = graph_body["entities"][0]["id"]
        entity = api_client.get(f"/api/graph/entities/{entity_id}")
        assert entity.status_code == 200
        assert entity.json()["id"] == entity_id

        queried = api_client.get(
            "/api/graph/query",
            params={"question": "安吉县竹产业链有哪些环节？", "county": "安吉县"},
        )
        assert queried.status_code == 200
        assert queried.json()["query"]

    def test_sse_stream_replays_and_ends(self, api_client):
        run_id = _start_run(api_client)["run_id"]
        _wait_for_run(api_client, run_id)

        with api_client.stream(
            "GET", f"/api/research/runs/{run_id}/events", params={"after": 0}
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            text = "".join(response.iter_text())

        assert "event: run_started" in text
        assert "event: agent_completed" in text
        assert "event: run_completed" in text
        assert "event: stream_end" in text
        assert '"run_id"' in text

        # Last-Event-ID 增量重放：只返回后续事件
        events = api_client.get(f"/api/research/runs/{run_id}").json()
        assert events["status"] == "completed"

    def test_resume_completed_run_is_idempotent(self, api_client):
        run_id = _start_run(api_client)["run_id"]
        _wait_for_run(api_client, run_id)
        resumed = api_client.post(f"/api/research/runs/{run_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"


class TestValidationAndErrors:
    def test_county_is_required_and_bounded(self, api_client):
        assert api_client.post("/api/research/runs", json={"county": "安"}).status_code == 422
        assert api_client.post("/api/research/runs", json={}).status_code == 422
        assert (
            api_client.post(
                "/api/research/runs", json={"county": "安吉县", "objectives": ["x"] * 11}
            ).status_code
            == 422
        )

    def test_unknown_run_returns_404(self, api_client):
        assert api_client.get("/api/research/runs/run-missing").status_code == 404
        assert api_client.get("/api/research/runs/run-missing/report").status_code == 404
        assert api_client.get("/api/evidence/runs/run-missing").status_code == 404
        assert api_client.post("/api/research/runs/run-missing/resume").status_code == 404
        assert api_client.get("/api/reports/run-missing").status_code == 404

    def test_unknown_entity_returns_404(self, api_client):
        assert api_client.get("/api/graph/entities/missing").status_code == 404

    def test_graph_query_requires_question(self, api_client):
        assert api_client.get("/api/graph/query").status_code == 422
        assert api_client.get("/api/graph/query", params={"question": "x"}).status_code == 422


class TestSimulations:
    def test_capabilities(self, api_client):
        response = api_client.get("/api/simulations/capabilities")
        assert response.status_code == 200
        body = response.json()
        assert body["engine"] == "baseline"
        assert body["calibrated"] is False
        assert "mesa_boundary" in body

    def test_baseline_simulation(self, api_client):
        payload = {
            "baseline": {
                "county": "安吉县",
                "industry": "竹产业",
                "output_yi": 100,
                "growth_rate": 0.1,
                "employment": 10000,
                "enterprise_count": 80,
                "source_year": 2025,
                "evidence_ids": ["ev-1"],
                "verification_status": "verified",
            },
            "scenario": {
                "name": "投资冲击",
                "horizon_years": 2,
                "shocks": {"investment_yi": 10},
            },
        }
        response = api_client.post("/api/simulations", json=payload)
        assert response.status_code == 200, response.text
        outcome = response.json()
        assert outcome["verification_status"] == "inferred"
        assert outcome["projections"][2]["output_yi"] == pytest.approx(142)
        assert outcome["assumptions"]

    def test_invalid_horizon_rejected(self, api_client):
        payload = {
            "baseline": {
                "county": "安吉县",
                "industry": "竹产业",
                "output_yi": 100,
            },
            "scenario": {"name": "too long", "horizon_years": 21},
        }
        assert api_client.post("/api/simulations", json=payload).status_code == 422
