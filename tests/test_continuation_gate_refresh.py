from __future__ import annotations

import json
from pathlib import Path

from scripts.refresh_continuation_gate import refresh_gate


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    authorization = {
        "authorization_id": "test-auth",
        "status": "ACTIVE_FREE_ONLY",
        "authorization": {
            "source": "current user instruction",
            "method": "manual_user_confirmation",
            "account_scope": "current_api_account",
            "evidence_ref": "test",
            "verified_at": "2026-10-19T01:13:10+08:00",
        },
        "providers": {
            provider: {
                "provider": provider,
                "billing_boundary": "FREE_CONFIRMED",
                "free_only": True,
                "paid_overage_allowed": False,
                "auto_switch_paid": False,
            }
            for provider in ("gemini", "tavily")
        },
    }
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    precheck_path = tmp_path / "precheck.json"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps({"status": "BLOCKED_PROVIDER_CONFIGURATION"}), encoding="utf-8")
    return authorization_path, precheck_path, gate_path


def test_refresh_gate_reopens_only_after_fresh_provider_checks(monkeypatch, tmp_path):
    authorization_path, precheck_path, gate_path = _write_inputs(tmp_path)
    monkeypatch.setattr(
        "scripts.refresh_continuation_gate.load_settings",
        lambda: object(),
    )
    monkeypatch.setattr(
        "scripts.refresh_continuation_gate.build_precheck",
        lambda **_: {
            "gemini": {
                "models_list_http_status": 200,
                "target_model_visible": True,
            },
            "tavily": {
                "status": "FREE_PLAN_USAGE_VISIBLE",
                "conservative_remaining_credits": 10,
                "paygo_usage_credits": 0,
            },
        },
    )

    result = refresh_gate(
        authorization_path=authorization_path,
        precheck_path=precheck_path,
        gate_path=gate_path,
    )

    assert result["status"] == "READY_FOR_PREFLIGHT"
    assert json.loads(gate_path.read_text(encoding="utf-8"))["business_api_calls_allowed"] is True


def test_refresh_gate_keeps_provider_blocked_when_model_is_not_visible(monkeypatch, tmp_path):
    authorization_path, precheck_path, gate_path = _write_inputs(tmp_path)
    monkeypatch.setattr("scripts.refresh_continuation_gate.load_settings", lambda: object())
    monkeypatch.setattr(
        "scripts.refresh_continuation_gate.build_precheck",
        lambda **_: {
            "gemini": {"models_list_http_status": 400, "target_model_visible": False},
            "tavily": {
                "status": "FREE_PLAN_USAGE_VISIBLE",
                "conservative_remaining_credits": 10,
                "paygo_usage_credits": 0,
            },
        },
    )

    result = refresh_gate(
        authorization_path=authorization_path,
        precheck_path=precheck_path,
        gate_path=gate_path,
    )

    assert result["status"] == "BLOCKED_PROVIDER_CONFIGURATION"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["business_api_calls_allowed"] is False
    assert gate["blocked_providers"] == ["gemini"]
