from __future__ import annotations

import json

import pytest
from scripts.precheck_independent_resources import (
    apply_deepseek_billing_evidence,
    apply_free_only_authorization,
    check_deepseek_configuration,
    check_gemini_models,
    check_tavily_usage,
)


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    requests: list[dict] = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def get(self, url, *, headers=None, params=None):
        self.requests.append({"url": url, "headers": headers, "params": params})
        if url.endswith("/models"):
            return _Response(
                200,
                {"models": [{"name": "models/gemini-3.1-flash-lite"}]},
            )
        return _Response(
            200,
            {
                "current_plan": "Researcher",
                "plan_usage_credits": 230,
                "plan_limit_credits": 1000,
                "paygo_usage_credits": 0,
            },
        )


def test_gemini_precheck_reports_visibility_without_claiming_billing(
    monkeypatch,
):
    _Client.requests = []
    result = check_gemini_models(
        api_key="secret-gemini-key",
        target_model="gemini-3.1-flash-lite",
        client_factory=_Client,
    )

    assert result["models_list_http_status"] == 200
    assert result["target_model_visible"] is True
    assert result["billing_boundary"] == "UNKNOWN"
    assert "secret-gemini-key" not in json.dumps(result)
    assert _Client.requests[0]["params"] == {"key": "secret-gemini-key"}


def test_tavily_precheck_normalizes_free_plan_usage_without_logging_key():
    _Client.requests = []
    result = check_tavily_usage(
        api_key="secret-tavily-key",
        client_factory=_Client,
    )

    assert result == {
        "usage_http_status": 200,
        "current_plan": "Researcher",
        "plan_usage_credits": 230,
        "plan_limit_credits": 1000,
        "conservative_remaining_credits": 770,
        "paygo_usage_credits": 0,
        "status": "FREE_PLAN_USAGE_VISIBLE",
    }
    assert "secret-tavily-key" not in json.dumps(result)
    assert _Client.requests[0]["headers"] == {"Authorization": "Bearer secret-tavily-key"}


def test_gemini_precheck_preserves_http_failure_without_inference():
    class ErrorClient(_Client):
        def get(self, url, *, headers=None, params=None):
            return _Response(403, {"error": {"message": "forbidden"}})

    result = check_gemini_models(
        api_key="secret-gemini-key",
        target_model="gemini-3.1-flash-lite",
        client_factory=ErrorClient,
    )

    assert result["models_list_http_status"] == 403
    assert result["target_model_visible"] is False
    assert result["billing_boundary"] == "UNKNOWN"
    assert result["status"] == "HTTP_ERROR"


def test_tavily_precheck_reads_nested_account_usage_shape():
    class NestedClient(_Client):
        def get(self, url, *, headers=None, params=None):
            return _Response(
                200,
                {
                    "account": {
                        "current_plan": "Researcher",
                        "plan_usage": 230,
                        "plan_limit": 1000,
                        "paygo_usage": 0,
                    },
                    "key": {"usage": 230},
                },
            )

    result = check_tavily_usage(
        api_key="secret-tavily-key",
        client_factory=NestedClient,
    )

    assert result["current_plan"] == "Researcher"
    assert result["plan_usage_credits"] == 230
    assert result["plan_limit_credits"] == 1000
    assert result["conservative_remaining_credits"] == 770
    assert result["paygo_usage_credits"] == 0
    assert result["status"] == "FREE_PLAN_USAGE_VISIBLE"


def test_deepseek_precheck_reports_configuration_without_inferencing_free_access():
    result = check_deepseek_configuration(
        llm_provider="deepseek",
        model="deepseek-chat",
        llm_api_key="secret-deepseek-key",
        search_provider="deepseek",
        search_api_key="secret-deepseek-key",
        search_enabled=True,
    )

    assert result == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "configured": True,
        "enabled": True,
        "llm_billing_boundary": "UNKNOWN",
        "search_fetch_billing_boundary": "UNKNOWN",
        "status": "CONFIGURED_BILLING_UNCONFIRMED",
    }
    assert "secret-deepseek-key" not in json.dumps(result)


def test_deepseek_precheck_applies_separate_operator_evidence_scopes():
    base = check_deepseek_configuration(
        llm_provider="deepseek",
        model="deepseek-chat",
        llm_api_key="secret-deepseek-key",
        search_provider="deepseek",
        search_api_key="secret-deepseek-key",
        search_enabled=True,
    )
    evidence = {
        "llm": {
            "billing_boundary": "FREE_CONFIRMED",
            "billing_evidence": {
                "source": "authenticated account console",
                "method": "account_level_check",
                "account_scope": "api_key_account",
                "evidence_ref": "llm-evidence",
                "verified_at": "2026-10-18T00:00:00+00:00",
            },
        },
        "search_fetch": {
            "billing_boundary": "FREE_CONFIRMED",
            "billing_evidence": {
                "source": "authenticated account console",
                "method": "search_fetch_policy_check",
                "account_scope": "api_key_account",
                "evidence_ref": "search-evidence",
                "verified_at": "2026-10-18T00:00:00+00:00",
            },
        },
    }

    result = apply_deepseek_billing_evidence(base, evidence)

    assert result["llm_billing_boundary"] == "FREE_CONFIRMED"
    assert result["search_fetch_billing_boundary"] == "FREE_CONFIRMED"
    assert result["llm_billing_evidence"]["evidence_ref"] == "llm-evidence"
    assert result["search_fetch_billing_evidence"]["evidence_ref"] == "search-evidence"


def test_deepseek_precheck_rejects_evidence_missing_one_scope():
    base = check_deepseek_configuration(
        llm_provider="deepseek",
        model="deepseek-chat",
        llm_api_key="secret-deepseek-key",
        search_provider="deepseek",
        search_api_key="secret-deepseek-key",
        search_enabled=True,
    )

    with pytest.raises(ValueError, match="search_fetch"):
        apply_deepseek_billing_evidence(
            base,
            {
                "llm": {
                    "billing_boundary": "FREE_CONFIRMED",
                    "billing_evidence": {
                        "source": "authenticated account console",
                        "method": "account_level_check",
                        "account_scope": "api_key_account",
                        "evidence_ref": "llm-evidence",
                        "verified_at": "2026-10-18T00:00:00+00:00",
                    },
                }
            },
        )


def test_free_only_authorization_marks_provider_without_inventing_balance():
    base = {
        "gemini": {
            "provider": "gemini",
            "model": "gemini-3.1-flash-lite",
            "billing_boundary": "UNKNOWN",
            "target_model_visible": False,
        },
        "tavily": {
            "status": "FREE_PLAN_USAGE_VISIBLE",
            "conservative_remaining_credits": 770,
            "paygo_usage_credits": 0,
        },
    }
    authorization = {
        "status": "ACTIVE_FREE_ONLY",
        "authorization": {
            "source": "current user instruction",
            "method": "manual_user_confirmation",
            "account_scope": "current_api_account",
            "evidence_ref": "user-message-2026-10-19-free-quota",
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

    result = apply_free_only_authorization(base, authorization)

    assert result["gemini"]["billing_boundary"] == "FREE_CONFIRMED"
    assert result["gemini"]["billing_basis"] == "user_attested_free_only"
    assert result["gemini"]["model_validation"] == "LIVE_CALL_REQUIRED"
    assert result["tavily"]["billing_boundary"] == "FREE_CONFIRMED"
    assert result["tavily"]["conservative_remaining_credits"] == 770
    assert result["tavily"]["paygo_usage_credits"] == 0


def test_free_only_authorization_rejects_paid_overage_or_auto_switch():
    with pytest.raises(ValueError, match="paid_overage_allowed"):
        apply_free_only_authorization(
            {"gemini": {}, "tavily": {}},
            {
                "status": "ACTIVE_FREE_ONLY",
                "authorization": {
                    "source": "current user instruction",
                    "method": "manual_user_confirmation",
                    "account_scope": "current_api_account",
                    "evidence_ref": "test",
                    "verified_at": "2026-10-19T01:13:10+08:00",
                },
                "providers": {
                    "gemini": {
                        "provider": "gemini",
                        "billing_boundary": "FREE_CONFIRMED",
                        "free_only": True,
                        "paid_overage_allowed": True,
                        "auto_switch_paid": False,
                    },
                    "tavily": {
                        "provider": "tavily",
                        "billing_boundary": "FREE_CONFIRMED",
                        "free_only": True,
                        "paid_overage_allowed": False,
                        "auto_switch_paid": False,
                    },
                },
            },
        )
