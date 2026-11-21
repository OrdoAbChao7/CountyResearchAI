"""Web 骨架测试：健康检查、启动元信息与 Web 配置。"""
from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from county_research_ai.web.app import create_app
from county_research_ai.web.settings import WebSettings


def _client(settings, web_settings: WebSettings | None = None) -> TestClient:
    return TestClient(
        create_app(settings=settings, web_settings=web_settings or WebSettings())
    )


def test_health_endpoint_reports_version(tmp_settings) -> None:
    response = _client(tmp_settings).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": tmp_settings.app.version,
        "active_runs": 0,
    }


def test_meta_reports_mock_without_api_keys(tmp_settings_no_key) -> None:
    response = _client(tmp_settings_no_key).get("/api/v1/meta")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == tmp_settings_no_key.app.version
    assert body["modes"] == ["snapshot", "rise-fall", "long-history"]
    assert body["features"] == {"deep_research": True, "sse": False, "graph": True}
    assert body["llm"] == {"configured": False, "provider": "mock"}
    assert body["search"] == {"configured": False, "provider": "mock"}
    assert body["limits"] == {
        "max_workers": 2,
        "queue_limit": 20,
        "max_graph_nodes": 1000,
    }


def test_meta_reports_configured_providers(tmp_settings) -> None:
    settings = tmp_settings.model_copy(
        update={
            "llm": tmp_settings.llm.model_copy(
                update={"api_key": SecretStr("llm-key")}
            ),
        }
    )

    body = _client(settings).get("/api/v1/meta").json()

    assert body["llm"] == {"configured": True, "provider": settings.llm.provider}
    assert body["search"] == {
        "configured": True,
        "provider": settings.search.provider,
    }


def test_web_settings_reads_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COUNTY_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("COUNTY_WEB_PORT", "9000")
    monkeypatch.setenv("COUNTY_WEB_WORKERS", "4")
    monkeypatch.setenv("COUNTY_WEB_QUEUE_LIMIT", "5")
    monkeypatch.setenv("COUNTY_WEB_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv(
        "COUNTY_WEB_CORS_ORIGINS", "http://localhost:5173, https://example.com"
    )
    monkeypatch.setenv("COUNTY_WEB_TOKEN", "secret-token")
    monkeypatch.setenv("COUNTY_WEB_EVENT_HEARTBEAT", "30")
    monkeypatch.setenv("COUNTY_WEB_EVENT_POLL", "0.5")
    monkeypatch.setenv("COUNTY_WEB_STATIC_DIR", str(tmp_path / "static"))

    web = WebSettings.from_env()

    assert web.host == "0.0.0.0"
    assert web.port == 9000
    assert web.workers == 4
    assert web.queue_limit == 5
    assert web.runs_dir == tmp_path / "runs"
    assert web.cors_origins == ["http://localhost:5173", "https://example.com"]
    assert web.token == "secret-token"
    assert web.event_heartbeat == 30
    assert web.event_poll == 0.5
    assert web.static_dir == tmp_path / "static"


def test_web_settings_treat_empty_values_as_defaults(monkeypatch) -> None:
    monkeypatch.setenv("COUNTY_WEB_PORT", "")
    monkeypatch.setenv("COUNTY_WEB_RUNS_DIR", "")
    monkeypatch.setenv("COUNTY_WEB_CORS_ORIGINS", "")

    web = WebSettings.from_env()

    assert web.port == 8000
    assert web.runs_dir == WebSettings().runs_dir
    assert web.cors_origins == []


def test_cors_is_enabled_only_when_origins_are_configured(tmp_settings) -> None:
    origin = "http://localhost:5173"
    headers = {"Origin": origin, "Access-Control-Request-Method": "GET"}

    enabled = _client(tmp_settings, WebSettings(cors_origins=[origin]))
    response = enabled.options("/api/health", headers=headers)
    assert response.headers.get("access-control-allow-origin") == origin

    disabled = _client(tmp_settings, WebSettings())
    response = disabled.options("/api/health", headers=headers)
    assert "access-control-allow-origin" not in response.headers
