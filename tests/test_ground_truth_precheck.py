from __future__ import annotations

from types import SimpleNamespace

from pydantic import SecretStr
from scripts.precheck_ground_truth_resources import build_ground_truth_precheck


def _settings(*, llm_provider: str, search_provider: str, key: str, enabled: bool):
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider=llm_provider,
            model="deepseek-flash" if llm_provider == "deepseek" else "gemini-3.1-flash-lite",
            base_url="https://api.deepseek.com/v1" if llm_provider == "deepseek" else "https://example.invalid",
            api_key=SecretStr(key),
        ),
        search=SimpleNamespace(
            provider=search_provider,
            deepseek_enabled=enabled,
            api_key=SecretStr(key),
        ),
    )


def test_precheck_reports_ready_without_logging_secret_values():
    payload = build_ground_truth_precheck(
        settings=_settings(
            llm_provider="deepseek",
            search_provider="deepseek",
            key="secret-value",
            enabled=True,
        ),
        checked_at="2026-10-18T00:00:00+00:00",
    )

    assert payload["status"] == "READY_FOR_GROUND_TRUTH"
    assert payload["deepseek"]["llm_configured"] is True
    assert payload["deepseek"]["search_enabled"] is True
    assert "secret-value" not in str(payload)


def test_precheck_blocks_gemini_tavily_mismatch():
    payload = build_ground_truth_precheck(
        settings=_settings(
            llm_provider="gemini",
            search_provider="tavily",
            key="secret-value",
            enabled=False,
        ),
        checked_at="2026-10-18T00:00:00+00:00",
    )

    assert payload["status"] == "BLOCKED_ENV_MISMATCH"
    assert payload["deepseek"]["llm_configured"] is False
    assert payload["deepseek"]["search_configured"] is False
