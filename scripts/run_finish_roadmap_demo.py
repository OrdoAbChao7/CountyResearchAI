"""Run the Anji bamboo MOCK demo end to end and write a summary artifact.

This script uses the real API application in-process (FastAPI TestClient), so
the demo exercises the same JobStore, JobRunner, event sink, evidence graph and
projections as the browser. It never calls a paid provider: ``live_enabled`` is
forced off, and the API labels the run ``MOCK``.

Usage (from the repository root):

    PYTHONPATH=src python scripts/run_finish_roadmap_demo.py

Windows PowerShell:

    $env:PYTHONPATH="src"; python scripts/run_finish_roadmap_demo.py

The script writes ``summary.json`` plus SQLite/report artifacts under
``experiments/quality/finish_roadmap_demo/run``. Start the API with the same
DATA_DIR/REPORTS_DIR to inspect the run in the wizard.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "experiments" / "quality" / "finish_roadmap_demo" / "run"

CONTRACT = {
    "objective": "评估安吉县 2024 年竹产业发展现状与财政贡献",
    "regions": ["安吉县"],
    "research_focus": "竹产业",
    "mode": "snapshot",
    "date_window": {"start": "2024-01-01", "end": "2024-12-31"},
    "required_questions": [
        "2024 年安吉县竹产业总产值是多少？",
        "安吉县有哪些竹产业龙头企业和产业集群？",
        "安吉县发布了哪些支持竹产业发展的政策？",
    ],
    "evidence_thresholds": {
        "min_independent_sources": 1,
        "min_supported_claims": 1,
    },
    "budget": {
        "max_steps": 8,
        "max_search_calls": 3,
        "deadline_seconds": 300,
        "max_documents": 10,
    },
    "options": {"deep_research": True},
}

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "INTERRUPTED"}


def _write_summary(payload: dict[str, Any]) -> Path:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / "summary.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def main() -> int:
    os.environ.setdefault("AXIOMSCOPE_API_LIVE", "false")
    os.environ.setdefault("AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS", "0")
    os.environ["DATA_DIR"] = str(RUN_DIR / "data")
    os.environ["REPORTS_DIR"] = str(RUN_DIR / "reports")
    sys.path.insert(0, str(ROOT / "src"))

    from county_research_ai.api.app import create_app

    app = create_app(live_enabled=False)

    with TestClient(app) as client:
        created = client.post("/api/v1/research/tasks", json={"contract": CONTRACT})
        created.raise_for_status()
        job_id = created.json()["job_id"]

        deadline = time.monotonic() + 180
        detail: dict[str, Any] = {}
        while time.monotonic() < deadline:
            detail = client.get(f"/api/v1/research/tasks/{job_id}").json()
            if detail["status"] in TERMINAL:
                break
            time.sleep(0.5)
        else:
            raise SystemExit(f"demo task {job_id} did not finish within 180s")

        events = client.get(f"/api/v1/research/tasks/{job_id}/events").json()
        graph = client.get(
            f"/api/v1/research/tasks/{job_id}/graph",
            params={"max_nodes": 400, "max_edges": 800},
        )
        report = client.get(f"/api/v1/research/tasks/{job_id}/report.json")

    graph_meta = graph.json().get("meta", {}) if graph.status_code == 200 else {}
    report_data = report.json() if report.status_code == 200 else {}
    summary = {
        "job_id": job_id,
        "mode_label": detail.get("mode_label"),
        "status": detail.get("status"),
        "outcome": detail.get("outcome"),
        "outcome_reason": detail.get("outcome_reason"),
        "event_count": len(events),
        "event_types": [event["event_type"] for event in events],
        "graph": {
            "status": graph.status_code,
            "total_nodes": graph_meta.get("total_nodes"),
            "returned_nodes": graph_meta.get("returned_nodes"),
            "total_edges": graph_meta.get("total_edges"),
            "returned_edges": graph_meta.get("returned_edges"),
            "counts": graph_meta.get("counts"),
            "truncated": graph_meta.get("truncated"),
        },
        "report": {
            "status": report.status_code,
            "sections": [section["id"] for section in report_data.get("sections", [])],
            "verification": report_data.get("verification"),
            "citations": len(report_data.get("citations", [])),
            "conflicts": len(report_data.get("conflicts", [])),
            "gaps": len(report_data.get("gaps", [])),
        },
        "artifacts": {
            "data_dir": str(RUN_DIR / "data"),
            "reports_dir": str(RUN_DIR / "reports"),
        },
    }
    path = _write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nsummary: {path}")
    return 0 if detail.get("status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
