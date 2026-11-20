"""Run exactly one bounded, explicitly authorized LIVE research smoke.

This script drives the real FastAPI application in-process (the same JobStore,
JobRunner, evidence graph and projections as the browser). It is not a new
run manager and it does not change the production code path.

It must be invoked with ``--confirm-paid`` because it makes real paid calls. The
budget and provider assumptions are recorded in
``docs/goal/LIVE_SMOKE_COST_GATE.md``.

Usage (from the repository root):

    PYTHONPATH=src python scripts/run_live_smoke.py \
        --env-file E:/Projects/CountyResearchAI/.env --confirm-paid

The script never prints or writes API keys. Run artifacts go under
``experiments/quality/live_smoke_20261120/``; raw documents and the SQLite job
store stay in ``run/`` (ignored by Git).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT.parent / "CountyResearchAI" / ".env"
DEFAULT_RUN_ROOT = ROOT / "experiments" / "quality" / "live_smoke_20261120"
RUN_ROOT = Path(
    os.environ.get("LIVE_SMOKE_RUN_ROOT", str(DEFAULT_RUN_ROOT))
)
RUN_DIR = RUN_ROOT / "run"

MAX_LLM_CALLS = 3
MAX_SEARCH_CALLS = 24
MAX_OUTPUT_TOKENS = 2048
MAX_RESULTS_PER_SEARCH = 6
WALL_CLOCK_SECONDS = 480

CONTRACT = {
    "objective": "用公开资料核验安吉县 2024 年竹产业的总产值与龙头企业",
    "regions": ["安吉县"],
    "research_focus": "竹产业",
    "mode": "snapshot",
    "date_window": {"start": "2024-01-01", "end": "2024-12-31"},
    "required_questions": [
        "2024 年安吉县竹产业总产值是多少？",
        "安吉县有哪些竹产业龙头企业？",
    ],
    "evidence_thresholds": {
        "min_independent_sources": 1,
        "min_supported_claims": 1,
    },
    "budget": {
        "max_steps": 8,
        "max_search_calls": MAX_SEARCH_CALLS,
        "deadline_seconds": WALL_CLOCK_SECONDS,
        "max_documents": 10,
        "max_tokens": MAX_OUTPUT_TOKENS,
    },
    "options": {"deep_research": True},
}

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "INTERRUPTED"}


@dataclass
class BudgetGuard:
    """Thread-safe counters and hard caps for the one smoke run."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    started: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    search_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_seconds: float = 0.0
    search_seconds: float = 0.0
    violations: list[str] = field(default_factory=list)
    llm_events: list[dict[str, Any]] = field(default_factory=list)
    search_events: list[dict[str, Any]] = field(default_factory=list)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def _check_deadline(self) -> None:
        if self.elapsed() > WALL_CLOCK_SECONDS:
            self.violations.append("wall_clock_exceeded")
            raise RuntimeError(f"wall-clock budget exceeded ({WALL_CLOCK_SECONDS}s)")

    def before_llm(self) -> None:
        with self.lock:
            self._check_deadline()
            if self.llm_calls >= MAX_LLM_CALLS:
                self.violations.append("llm_call_cap")
                raise RuntimeError(f"LLM call cap reached ({MAX_LLM_CALLS})")
            self.llm_calls += 1

    def record_llm(self, response: Any, seconds: float) -> None:
        with self.lock:
            prompt = int(getattr(response, "prompt_tokens", 0) or 0)
            completion = int(getattr(response, "completion_tokens", 0) or 0)
            total = int(getattr(response, "total_tokens", 0) or 0)
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.total_tokens += total
            self.llm_seconds += seconds
            self.llm_events.append(
                {
                    "call": self.llm_calls,
                    "model": getattr(response, "model", ""),
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                    "seconds": round(seconds, 2),
                }
            )

    def before_search(self, query: str) -> None:
        with self.lock:
            self._check_deadline()
            if self.search_calls >= MAX_SEARCH_CALLS:
                self.violations.append("search_call_cap")
                raise RuntimeError(f"search call cap reached ({MAX_SEARCH_CALLS})")
            self.search_calls += 1

    def record_search(self, query: str, documents: int, seconds: float) -> None:
        with self.lock:
            self.search_seconds += seconds
            self.search_events.append(
                {
                    "call": self.search_calls,
                    "query_chars": len(query),
                    "documents": documents,
                    "seconds": round(seconds, 2),
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "llm_calls": self.llm_calls,
                "search_calls": self.search_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "llm_seconds": round(self.llm_seconds, 2),
                "search_seconds": round(self.search_seconds, 2),
                "elapsed_seconds": round(self.elapsed(), 2),
                "violations": list(self.violations),
                "llm_events": list(self.llm_events),
                "search_events": list(self.search_events),
            }


def load_env_file(path: Path) -> None:
    """Load an env file without printing values; existing env wins."""
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)


def install_guards(guard: BudgetGuard) -> None:
    """Cap real provider calls before the application container is built."""
    from county_research_ai.llm.client import OpenAICompatibleClient
    from county_research_ai.search.web_search import TavilySearchProvider

    original_chat = OpenAICompatibleClient.chat
    original_search = TavilySearchProvider.search

    def guarded_chat(
        self: Any,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any:
        guard.before_llm()
        capped = (
            MAX_OUTPUT_TOKENS
            if max_tokens is None
            else min(int(max_tokens), MAX_OUTPUT_TOKENS)
        )
        started = time.monotonic()
        response = original_chat(
            self,
            messages,
            temperature=temperature,
            max_tokens=capped,
            **kwargs,
        )
        guard.record_llm(response, time.monotonic() - started)
        return response

    def guarded_search(
        self: Any, query: str, max_results: int = 10
    ) -> list[Any]:
        guard.before_search(query)
        capped = min(int(max_results or 1), MAX_RESULTS_PER_SEARCH)
        started = time.monotonic()
        documents = original_search(self, query, max_results=capped)
        guard.record_search(query, len(documents), time.monotonic() - started)
        return documents

    OpenAICompatibleClient.chat = guarded_chat  # type: ignore[method-assign]
    TavilySearchProvider.search = guarded_search  # type: ignore[method-assign]


def build_settings(env_file: Path) -> Any:
    from county_research_ai.config import (
        LLMRetryConfig,
        SearchRetryConfig,
        load_settings,
    )

    load_env_file(env_file)
    # Process-level overrides. The root .env is not modified.
    os.environ["LLM_PROVIDER"] = "deepseek"
    os.environ["LLM_BASE_URL"] = "https://api.deepseek.com/v1"
    os.environ["LLM_MODEL"] = "deepseek-flash"
    os.environ["SEARCH_PROVIDER"] = "tavily"
    os.environ["AXIOMSCOPE_API_LIVE"] = "true"
    os.environ["DATA_DIR"] = str(RUN_DIR / "data")
    os.environ["REPORTS_DIR"] = str(RUN_DIR / "reports")
    os.environ["CACHE_TTL_HOURS"] = "0"

    settings = load_settings()
    llm = settings.llm.model_copy(
        update={
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash",
            "max_tokens": MAX_OUTPUT_TOKENS,
            "timeout": 90,
            "temperature": 0.0,
            "retry": LLMRetryConfig(max_attempts=1, backoff_seconds=0),
        }
    )
    search = settings.search.model_copy(
        update={
            "provider": "tavily",
            "max_results": 8,
            "timeout": 25,
            "concurrency": 3,
            "fetch_detail": False,
            "retry": SearchRetryConfig(max_attempts=1, backoff_seconds=0),
        }
    )
    return settings.model_copy(
        update={
            "llm": llm,
            "search": search,
            "pipeline": settings.pipeline.model_copy(update={"fail_fast": True}),
        }
    )


def verify_model_access(settings: Any) -> list[str]:
    """Free provider check: confirm the key and model without paid tokens."""
    import httpx

    key = settings.llm.api_key.get_secret_value()
    response = httpx.get(
        "https://api.deepseek.com/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=20.0,
    )
    response.raise_for_status()
    model_ids = [item.get("id", "") for item in response.json().get("data", [])]
    if settings.llm.model not in model_ids:
        raise SystemExit(
            f"configured model {settings.llm.model!r} not offered; available={model_ids}"
        )
    return model_ids


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--confirm-paid",
        action="store_true",
        help="required acknowledgement that this run spends real provider credits",
    )
    args = parser.parse_args()
    if not args.confirm_paid:
        raise SystemExit(
            "refusing to make paid calls without --confirm-paid; "
            "see docs/goal/LIVE_SMOKE_COST_GATE.md"
        )

    settings = build_settings(args.env_file)
    if not settings.llm.api_key.get_secret_value():
        raise SystemExit("LLM API key is empty after loading the env file")
    if not settings.search.api_key.get_secret_value():
        raise SystemExit("search API key is empty after loading the env file")

    model_ids = verify_model_access(settings)
    print(
        f"provider check: deepseek model={settings.llm.model} "
        f"available={','.join(model_ids)}"
    )

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    guard = BudgetGuard()
    install_guards(guard)

    from fastapi.testclient import TestClient

    from county_research_ai.api.app import create_app
    from county_research_ai.llm.client import OpenAICompatibleClient

    # Tiny preflight: verifies auth/model and exercises the guarded client.
    preflight_client = OpenAICompatibleClient(settings=settings)
    preflight = preflight_client.chat(
        [{"role": "user", "content": "Reply with exactly: LIVE_OK"}],
        temperature=0.0,
        max_tokens=16,
    )
    print(
        f"preflight: content_chars={len(preflight.content)} "
        f"model={preflight.model} tokens={preflight.total_tokens}"
    )

    app = create_app(settings=settings, live_enabled=True)
    summary: dict[str, Any] = {
        "date": "2026-11-20",
        "authorization": "user: 允许付费调用 + 跑一次 Live + 再跑一次 (2026-11-20)",
        "cost_gate": "docs/goal/LIVE_SMOKE_COST_GATE.md",
        "provider": {
            "llm": "deepseek",
            "model": settings.llm.model,
            "base_url": settings.llm.base_url,
            "search": settings.search.provider,
            "search_depth": "basic",
        },
        "model_ids": model_ids,
        "preflight": {
            "content_chars": len(preflight.content),
            "model": preflight.model,
            "total_tokens": preflight.total_tokens,
        },
    }

    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities")
        summary["capabilities"] = {
            "status": capabilities.status_code,
            "mode_label": capabilities.json().get("mode_label")
            if capabilities.status_code == 200
            else None,
        }
        created = client.post("/api/v1/research/tasks", json={"contract": CONTRACT})
        created.raise_for_status()
        job_id = created.json()["job_id"]
        summary["job_id"] = job_id
        print(f"job created: {job_id}")

        deadline = time.monotonic() + WALL_CLOCK_SECONDS
        detail: dict[str, Any] = {}
        while time.monotonic() < deadline:
            detail = client.get(f"/api/v1/research/tasks/{job_id}").json()
            if detail.get("status") in TERMINAL:
                break
            time.sleep(1.0)

        status = detail.get("status", "TIMEOUT")
        events_response = client.get(f"/api/v1/research/tasks/{job_id}/events")
        events = events_response.json() if events_response.status_code == 200 else []
        graph_response = client.get(
            f"/api/v1/research/tasks/{job_id}/graph",
            params={"max_nodes": 400, "max_edges": 800},
        )
        report_json_response = client.get(
            f"/api/v1/research/tasks/{job_id}/report.json"
        )
        report_md_response = client.get(f"/api/v1/research/tasks/{job_id}/report")
        sources_response = client.get(f"/api/v1/research/tasks/{job_id}/sources")

    graph_data = (
        graph_response.json() if graph_response.status_code == 200 else {}
    )
    graph_meta = graph_data.get("meta", {}) if isinstance(graph_data, dict) else {}
    report_data = (
        report_json_response.json()
        if report_json_response.status_code == 200
        else {}
    )
    sources_data = (
        sources_response.json() if sources_response.status_code == 200 else []
    )
    if isinstance(sources_data, dict):
        sources_list = sources_data.get("sources", [])
    else:
        sources_list = sources_data

    summary.update(
        {
            "status": status,
            "mode_label": detail.get("mode_label"),
            "outcome": detail.get("outcome"),
            "outcome_reason": detail.get("outcome_reason"),
            "budget_enforcement": detail.get("budget_enforcement"),
            "event_count": len(events),
            "event_types": [event.get("event_type") for event in events],
            "graph": {
                "http_status": graph_response.status_code,
                "total_nodes": graph_meta.get("total_nodes"),
                "returned_nodes": graph_meta.get("returned_nodes"),
                "total_edges": graph_meta.get("total_edges"),
                "returned_edges": graph_meta.get("returned_edges"),
                "truncated": graph_meta.get("truncated"),
            },
            "report": {
                "json_status": report_json_response.status_code,
                "markdown_status": report_md_response.status_code,
                "sections": [
                    section.get("id")
                    for section in report_data.get("sections", [])
                    if isinstance(section, dict)
                ],
                "verification": report_data.get("verification"),
                "citation_count": len(report_data.get("citations", [])),
                "conflict_count": len(report_data.get("conflicts", [])),
                "gap_count": len(report_data.get("gaps", [])),
            },
            "sources": {
                "http_status": sources_response.status_code,
                "count": len(sources_list),
                "items": [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "published_at": item.get("published_at"),
                    }
                    for item in sources_list[:20]
                    if isinstance(item, dict)
                ],
            },
            "guard": guard.snapshot(),
        }
    )

    live_ok = (
        status == "SUCCEEDED"
        and summary["mode_label"] == "LIVE"
        and guard.llm_calls >= 1
        and guard.search_calls >= 1
        and not guard.violations
    )
    verification = report_data.get("verification") or {}
    verified_count = int(verification.get("verified", 0) or 0)
    snapshot = guard.snapshot()
    summary["estimated_cost_usd"] = {
        "llm_offpeak": round(
            snapshot["prompt_tokens"] * 0.15 / 1_000_000
            + snapshot["completion_tokens"] * 0.60 / 1_000_000,
            6,
        ),
        "llm_peak_worst_case": round(
            snapshot["prompt_tokens"] * 0.30 / 1_000_000
            + snapshot["completion_tokens"] * 1.20 / 1_000_000,
            6,
        ),
        "tavily_if_paid": round(snapshot["search_calls"] * 0.008, 4),
        "total_if_tavily_paid": round(
            snapshot["prompt_tokens"] * 0.30 / 1_000_000
            + snapshot["completion_tokens"] * 1.20 / 1_000_000
            + snapshot["search_calls"] * 0.008,
            4,
        ),
    }
    summary["verdict_scope"] = "engineering_smoke_only"
    summary["research_verdict"] = (
        "HAS_SUPPORTED_CLAIMS" if verified_count > 0 else "NO_SUPPORTED_CLAIMS"
    )
    if not live_ok:
        summary["verdict"] = "FAIL"
    elif len(sources_list) == 0:
        summary["verdict"] = "PARTIAL"
        summary["verdict_reason"] = "job succeeded but no live sources were returned"
    elif not verification:
        summary["verdict"] = "PARTIAL"
        summary["verdict_reason"] = "report projection has no verification payload"
    else:
        summary["verdict"] = "PASS_ENGINEERING"
        if verified_count == 0:
            summary["verdict_reason"] = (
                "live plumbing works, but the verifier accepted zero claims"
            )

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(RUN_ROOT / "summary.json", summary)
    write_json(RUN_ROOT / "report.json", report_data)
    if report_md_response.status_code == 200:
        (RUN_ROOT / "report.md").write_text(
            report_md_response.text, encoding="utf-8"
        )
    write_json(RUN_DIR / "summary.json", summary)
    write_json(RUN_DIR / "events.json", events)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nsummary: {RUN_ROOT / 'summary.json'}")
    if summary["verdict"] == "PASS_ENGINEERING":
        return 0
    if summary["verdict"] == "PARTIAL":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
