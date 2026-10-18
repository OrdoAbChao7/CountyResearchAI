"""刷新独立实验资源预检，不调用任何业务模型或搜索请求。"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from county_research_ai.config import load_settings

GEMINI_MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TAVILY_USAGE_ENDPOINT = "https://api.tavily.com/usage"
ClientFactory = Callable[..., Any]
DEEPSEEK_BILLING_BOUNDARIES = {
    "FREE_CONFIRMED",
    "PAID_CONFIRMED",
    "USER_AUTHORIZED_PAID",
    "UNKNOWN",
}
_BILLING_EVIDENCE_FIELDS = (
    "source",
    "method",
    "account_scope",
    "evidence_ref",
    "verified_at",
)


def check_gemini_models(
    *,
    api_key: str,
    target_model: str,
    client_factory: ClientFactory = httpx.Client,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Check model visibility only; account billing is deliberately never inferred."""
    base = {
        "provider": "gemini",
        "model": target_model,
        "account_quota_fields_returned": False,
        "billing_boundary": "UNKNOWN",
    }
    if not api_key:
        return {**base, "models_list_http_status": None, "target_model_visible": False, "status": "API_KEY_MISSING"}
    try:
        with client_factory(timeout=timeout) as client:
            response = client.get(GEMINI_MODELS_ENDPOINT, params={"key": api_key})
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        return {
            **base,
            "models_list_http_status": None,
            "target_model_visible": False,
            "status": "ERROR",
            "error_type": type(exc).__name__,
        }
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = {
        str(item.get("name", "")).removeprefix("models/")
        for item in models
        if isinstance(item, dict)
    }
    visible = target_model in names
    if response.status_code >= 400:
        status = "HTTP_ERROR"
    elif visible:
        status = "MODEL_VISIBLE_ACCOUNT_BILLING_UNCONFIRMED"
    else:
        status = "TARGET_MODEL_NOT_VISIBLE"
    return {
        **base,
        "models_list_http_status": response.status_code,
        "target_model_visible": visible,
        "status": status,
    }


def check_tavily_usage(
    *,
    api_key: str,
    client_factory: ClientFactory = httpx.Client,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Read Tavily usage without exposing the key or assuming a free billing mode."""
    if not api_key:
        return {
            "usage_http_status": None,
            "current_plan": None,
            "plan_usage_credits": None,
            "plan_limit_credits": None,
            "conservative_remaining_credits": None,
            "paygo_usage_credits": None,
            "status": "API_KEY_MISSING",
        }
    try:
        with client_factory(timeout=timeout) as client:
            response = client.get(
                TAVILY_USAGE_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        return {
            "usage_http_status": None,
            "status": "ERROR",
            "error_type": type(exc).__name__,
        }
    data = payload if isinstance(payload, dict) else {}
    account = data.get("account") if isinstance(data.get("account"), dict) else data
    used = _credits(account, "plan_usage_credits", "plan_usage", "usage")
    limit = _credits(account, "plan_limit_credits", "plan_limit", "limit")
    paygo = _credits(account, "paygo_usage_credits", "paygo_usage")
    plan = account.get("current_plan") or account.get("plan")
    result: dict[str, Any] = {
        "usage_http_status": response.status_code,
        "current_plan": str(plan) if plan is not None else None,
        "plan_usage_credits": used,
        "plan_limit_credits": limit,
        "conservative_remaining_credits": (
            max(limit - used, 0) if used is not None and limit is not None else None
        ),
        "paygo_usage_credits": paygo,
    }
    if response.status_code >= 400:
        result["status"] = "HTTP_ERROR"
    elif plan and used is not None and limit is not None and paygo == 0:
        result["status"] = "FREE_PLAN_USAGE_VISIBLE"
    elif plan and used is not None and limit is not None:
        result["status"] = "PLAN_USAGE_VISIBLE_PAYGO_UNKNOWN"
    else:
        result["status"] = "USAGE_FIELDS_INCOMPLETE"
    return result


def check_deepseek_configuration(
    *,
    llm_provider: str,
    model: str,
    llm_api_key: str,
    search_provider: str,
    search_api_key: str,
    search_enabled: bool,
) -> dict[str, Any]:
    """Report local DeepSeek configuration without making a business call."""
    llm_active = llm_provider.lower() == "deepseek"
    search_active = search_provider.lower() == "deepseek"
    configured = (llm_active and bool(llm_api_key)) or (
        search_active and bool(search_api_key)
    )
    enabled = search_active and bool(search_enabled)
    return {
        "provider": "deepseek",
        "model": model if llm_active else None,
        "configured": configured,
        "enabled": enabled,
        "llm_billing_boundary": "UNKNOWN",
        "search_fetch_billing_boundary": "UNKNOWN",
        "status": (
            "CONFIGURED_BILLING_UNCONFIRMED"
            if configured
            else "DISABLED_BY_POLICY"
        ),
    }


def apply_deepseek_billing_evidence(
    base: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Attach separately scoped operator evidence without exposing credentials."""
    if not isinstance(evidence, dict):
        raise ValueError("DeepSeek billing evidence must be an object")
    result = dict(base)
    for scope in ("llm", "search_fetch"):
        entry = evidence.get(scope)
        if not isinstance(entry, dict):
            raise ValueError(f"DeepSeek evidence missing scope: {scope}")
        boundary = entry.get("billing_boundary")
        if boundary not in DEEPSEEK_BILLING_BOUNDARIES:
            raise ValueError(
                f"DeepSeek evidence has invalid billing boundary for scope: {scope}"
            )
        billing_evidence = entry.get("billing_evidence")
        if not isinstance(billing_evidence, dict) or any(
            not isinstance(billing_evidence.get(field), str)
            or not billing_evidence[field].strip()
            for field in _BILLING_EVIDENCE_FIELDS
        ):
            raise ValueError(
                f"DeepSeek evidence is missing auditable fields for scope: {scope}"
            )
        result[f"{scope if scope == 'llm' else 'search_fetch'}_billing_boundary"] = boundary
        result[f"{scope if scope == 'llm' else 'search_fetch'}_billing_evidence"] = dict(
            billing_evidence
        )
    return result


def build_precheck(
    *,
    settings: Any,
    checked_at: str | None = None,
    deepseek_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a machine-readable precheck record while keeping credentials out."""
    deepseek = check_deepseek_configuration(
        llm_provider=settings.llm.provider,
        model=settings.llm.model,
        llm_api_key=settings.llm.api_key.get_secret_value(),
        search_provider=settings.search.provider,
        search_api_key=settings.search.api_key.get_secret_value(),
        search_enabled=settings.search.deepseek_enabled,
    )
    if deepseek_evidence is not None:
        deepseek = apply_deepseek_billing_evidence(deepseek, deepseek_evidence)
    return {
        "check_id": "resource_precheck",
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
        "deepseek": deepseek,
        "gemini": check_gemini_models(
            api_key=settings.llm.api_key.get_secret_value(),
            target_model=settings.llm.model,
        ),
        "tavily": check_tavily_usage(
            api_key=settings.search.api_key.get_secret_value(),
        ),
        "formal_gate": "CLOSED_UNTIL_GEMINI_ACCOUNT_BILLING_BOUNDARY_CONFIRMED",
        "business_model_calls_made": False,
        "api_keys_logged": False,
    }


def _credits(data: dict[str, Any], *names: str) -> int | float | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, dict):
            nested = value.get("credits", value.get("value"))
            if isinstance(nested, (int, float)) and not isinstance(nested, bool):
                return nested
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deepseek-billing-evidence", type=Path)
    args = parser.parse_args()
    deepseek_evidence = None
    if args.deepseek_billing_evidence is not None:
        try:
            deepseek_evidence = json.loads(
                args.deepseek_billing_evidence.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read DeepSeek billing evidence: {exc}")
    payload = build_precheck(
        settings=load_settings(),
        deepseek_evidence=deepseek_evidence,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "status": payload["formal_gate"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
