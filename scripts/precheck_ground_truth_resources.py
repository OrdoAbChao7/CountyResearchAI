"""Create a non-secret precheck for the continuation Ground Truth API gate.

The precheck is intentionally local-only. It reads the resolved project
configuration and records whether the requested DeepSeek LLM and Search/Fetch
paths are configured; it does not make a business API call.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from county_research_ai.config import load_settings

EXPECTED_PROVIDER = "deepseek"
EXPECTED_MODEL = "deepseek-flash"


def build_ground_truth_precheck(
    *,
    settings: Any,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Return configuration facts needed by the Ground Truth-only gate."""
    llm_provider = str(settings.llm.provider).lower()
    search_provider = str(settings.search.provider).lower()
    llm_key_present = bool(settings.llm.api_key.get_secret_value())
    search_key_present = bool(settings.search.api_key.get_secret_value())
    llm_configured = llm_provider == EXPECTED_PROVIDER and llm_key_present
    search_configured = search_provider == EXPECTED_PROVIDER and search_key_present
    search_enabled = search_configured and bool(settings.search.deepseek_enabled)
    ready = llm_configured and search_enabled
    return {
        "check_id": "continuation_ground_truth_precheck_20261018",
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_GROUND_TRUTH" if ready else "BLOCKED_ENV_MISMATCH",
        "expected": {
            "llm_provider": EXPECTED_PROVIDER,
            "search_provider": EXPECTED_PROVIDER,
            "historical_model_target": EXPECTED_MODEL,
        },
        "deepseek": {
            "provider": EXPECTED_PROVIDER,
            "model": settings.llm.model if llm_provider == EXPECTED_PROVIDER else EXPECTED_MODEL,
            "llm_configured": llm_configured,
            "search_configured": search_configured,
            "search_enabled": search_enabled,
            "observed_llm_provider": llm_provider,
            "observed_llm_model": str(settings.llm.model),
            "observed_llm_base_url": str(settings.llm.base_url),
            "observed_search_provider": search_provider,
            "api_keys_logged": False,
        },
        "business_calls_made": False,
        "api_keys_logged": False,
    }


def build_ground_truth_gate(
    *,
    precheck: dict[str, Any],
    authorization_verified_at: str | None = None,
) -> dict[str, Any]:
    """Build a task-scoped gate without asserting account prices or quotas."""
    deepseek = precheck["deepseek"]
    ready = precheck.get("status") == "READY_FOR_GROUND_TRUTH"
    return {
        "gate_id": "continuation_ground_truth_gate_20261018",
        "status": "READY_FOR_GROUND_TRUTH" if ready else "BLOCKED_ENV_MISMATCH",
        "created_at": precheck["checked_at"],
        "scope": ["ground_truth_collection"],
        "business_api_calls_allowed": ready,
        "allow_paid_authorized": True,
        "llm_provider": "deepseek",
        "search_provider": "deepseek",
        "model": deepseek["model"],
        "authorization": {
            "source": "current user instruction",
            "method": "explicit_current_user_authorization",
            "account_scope": "current_task",
            "evidence_ref": "user-message-current-ground-truth",
            "verified_at": authorization_verified_at or precheck["checked_at"],
        },
        "resource_precheck": "continuation_ground_truth_precheck_20261018.json",
        "api_keys_logged": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings()
    precheck = build_ground_truth_precheck(settings=settings)
    gate = build_ground_truth_gate(precheck=precheck)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "continuation_ground_truth_precheck_20261018.json").write_text(
        json.dumps(precheck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "continuation_ground_truth_gate_20261018.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": gate["status"], "api_keys_logged": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
