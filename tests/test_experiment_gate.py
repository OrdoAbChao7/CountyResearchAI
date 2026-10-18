from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from county_research_ai.evaluation.gate import (
    FormalGateError,
    require_formal_api_gate,
    require_frozen_ground_truth,
    require_frozen_launch_manifest,
    require_ground_truth_collection_gate,
)
from county_research_ai.evaluation.ground_truth import GroundTruthClaim, GroundTruthStore


def _write_gate(
    tmp_path,
    *,
    gate_status="NOT_RUN",
    billing_boundary="UNKNOWN",
    checked_at=None,
    billing_evidence=None,
    tavily_remaining=1,
    tavily_paygo=0,
):
    gate = {
        "status": gate_status,
        "resource_precheck": "resource_precheck.json",
        "model": "gemini-3.1-flash-lite",
    }
    precheck = {
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
        "gemini": {
            "provider": "gemini",
            "model": "gemini-3.1-flash-lite",
            "models_list_http_status": 200,
            "target_model_visible": True,
            "billing_boundary": billing_boundary,
        },
        "tavily": {
            "usage_http_status": 200,
            "status": "FREE_PLAN_USAGE_VISIBLE",
            "conservative_remaining_credits": tavily_remaining,
            "paygo_usage_credits": tavily_paygo,
        },
    }
    if billing_evidence is not None:
        precheck["gemini"]["billing_evidence"] = billing_evidence
    gate_path = tmp_path / "gate.json"
    precheck_path = tmp_path / "resource_precheck.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    precheck_path.write_text(json.dumps(precheck), encoding="utf-8")
    return gate_path, precheck_path


def _write_deepseek_gate(
    tmp_path,
    *,
    llm_boundary="FREE_CONFIRMED",
    search_fetch_boundary="FREE_CONFIRMED",
):
    evidence = {
        "source": "authenticated account console",
        "method": "account_level_check",
        "account_scope": "api_key_account",
        "evidence_ref": "deepseek-test-evidence",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    gate = {
        "status": "READY_FOR_PREFLIGHT",
        "resource_precheck": "resource_precheck.json",
        "llm_provider": "deepseek",
        "model": "deepseek-chat",
        "search_provider": "deepseek",
    }
    precheck = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "deepseek": {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "configured": True,
            "enabled": True,
            "llm_billing_boundary": llm_boundary,
            "search_fetch_billing_boundary": search_fetch_boundary,
            "llm_billing_evidence": evidence,
            "search_fetch_billing_evidence": evidence,
        },
    }
    gate_path = tmp_path / "deepseek-gate.json"
    precheck_path = tmp_path / "resource_precheck.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    precheck_path.write_text(json.dumps(precheck), encoding="utf-8")
    return gate_path, precheck_path


def test_formal_api_gate_rejects_closed_gate(tmp_path):
    gate_path, precheck_path = _write_gate(tmp_path)

    with pytest.raises(FormalGateError, match="gate is not open"):
        require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_rejects_unknown_account_billing(tmp_path):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="UNKNOWN",
    )

    with pytest.raises(FormalGateError, match="billing boundary"):
        require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_accepts_only_ready_free_confirmed_state(tmp_path):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        billing_evidence={
            "source": "authenticated account console",
            "method": "account_level_check",
            "account_scope": "api_key_account",
            "evidence_ref": "test-evidence",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_accepts_user_attested_free_only_provider_scope(tmp_path):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        billing_evidence={
            "source": "current user instruction",
            "method": "manual_user_confirmation",
            "account_scope": "current_api_account",
            "evidence_ref": "user-message-2026-10-19-free-quota",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["authorization_manifest"] = "authorization.json"
    gate["allow_paid_authorized"] = False
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    authorization = {
        "status": "ACTIVE_FREE_ONLY",
        "authorization": {
            "source": "current user instruction",
            "method": "manual_user_confirmation",
            "account_scope": "current_api_account",
            "evidence_ref": "user-message-2026-10-19-free-quota",
            "verified_at": datetime.now(timezone.utc).isoformat(),
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
    (tmp_path / "authorization.json").write_text(
        json.dumps(authorization), encoding="utf-8"
    )

    result = require_formal_api_gate(gate_path, precheck_path)

    assert result["gate"]["allow_paid_authorized"] is False


def test_deepseek_gate_requires_separate_free_evidence_for_llm_and_search_fetch(
    tmp_path,
):
    gate_path, precheck_path = _write_deepseek_gate(tmp_path)

    result = require_formal_api_gate(gate_path, precheck_path)

    assert result["precheck"]["deepseek"]["provider"] == "deepseek"


def test_deepseek_gate_rejects_historical_user_authorized_paid_boundary(tmp_path):
    gate_path, precheck_path = _write_deepseek_gate(
        tmp_path,
        llm_boundary="USER_AUTHORIZED_PAID",
        search_fetch_boundary="USER_AUTHORIZED_PAID",
    )

    with pytest.raises(FormalGateError, match="billing boundary"):
        require_formal_api_gate(gate_path, precheck_path)


def test_continuation_gate_manifest_uses_current_free_only_authorization():
    path = (
        Path(__file__).parents[1]
        / "experiments"
        / "independent_comparison"
        / "manifests"
        / "continuation_resource_gate_20261018.json"
    )
    gate = json.loads(path.read_text(encoding="utf-8"))

    assert gate["status"] == "BLOCKED_PROVIDER_CONFIGURATION"
    assert gate["business_api_calls_allowed"] is False
    assert gate["allow_paid_authorized"] is False
    assert gate["free_only"] is True
    assert gate["account_balance_query_unavailable_is_global_blocker"] is False
    assert gate["blocked_providers"] == ["gemini"]


def test_ground_truth_collection_gate_accepts_currently_authorized_paid_scope(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    gate = {
        "status": "READY_FOR_GROUND_TRUTH",
        "business_api_calls_allowed": True,
        "allow_paid_authorized": True,
        "scope": ["ground_truth_collection"],
        "llm_provider": "deepseek",
        "search_provider": "deepseek",
        "model": "deepseek-flash",
        "authorization": {
            "source": "current user instruction",
            "method": "explicit_current_user_authorization",
            "account_scope": "current_task",
            "evidence_ref": "user-message-current-ground-truth",
            "verified_at": now,
        },
        "resource_precheck": "precheck.json",
    }
    precheck = {
        "checked_at": now,
        "deepseek": {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "llm_configured": True,
            "search_configured": True,
            "search_enabled": True,
        },
    }
    gate_path = tmp_path / "gate.json"
    precheck_path = tmp_path / "precheck.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    precheck_path.write_text(json.dumps(precheck), encoding="utf-8")

    result = require_ground_truth_collection_gate(gate_path, precheck_path)

    assert result["gate"]["status"] == "READY_FOR_GROUND_TRUTH"


def test_ground_truth_collection_gate_rejects_provider_mismatch(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    gate = {
        "status": "READY_FOR_GROUND_TRUTH",
        "business_api_calls_allowed": True,
        "allow_paid_authorized": True,
        "scope": ["ground_truth_collection"],
        "llm_provider": "deepseek",
        "search_provider": "deepseek",
        "model": "deepseek-flash",
        "authorization": {
            "source": "current user instruction",
            "method": "explicit_current_user_authorization",
            "account_scope": "current_task",
            "evidence_ref": "user-message-current-ground-truth",
            "verified_at": now,
        },
        "resource_precheck": "precheck.json",
    }
    precheck = {
        "checked_at": now,
        "deepseek": {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "llm_configured": False,
            "search_configured": False,
            "search_enabled": False,
        },
    }
    gate_path = tmp_path / "gate.json"
    precheck_path = tmp_path / "precheck.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    precheck_path.write_text(json.dumps(precheck), encoding="utf-8")

    with pytest.raises(FormalGateError, match="not configured"):
        require_ground_truth_collection_gate(gate_path, precheck_path)


def test_deepseek_gate_rejects_llm_free_when_search_fetch_billing_is_unknown(tmp_path):
    gate_path, precheck_path = _write_deepseek_gate(
        tmp_path,
        search_fetch_boundary="UNKNOWN",
    )

    with pytest.raises(FormalGateError, match="Search/Fetch billing boundary"):
        require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_rejects_stale_resource_precheck(tmp_path):
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        checked_at=stale,
        billing_evidence={
            "source": "authenticated account console",
            "method": "account_level_check",
            "account_scope": "api_key_account",
            "evidence_ref": "test-evidence",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    with pytest.raises(FormalGateError, match="stale"):
        require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_rejects_unverifiable_free_confirmation(tmp_path):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
    )

    with pytest.raises(FormalGateError, match="billing evidence"):
        require_formal_api_gate(gate_path, precheck_path)


def test_formal_api_gate_rejects_stale_billing_evidence(tmp_path):
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        billing_evidence={
            "source": "authenticated account console",
            "method": "account_level_check",
            "account_scope": "api_key_account",
            "evidence_ref": "test-evidence",
            "verified_at": stale,
        },
    )

    with pytest.raises(FormalGateError, match="billing evidence is stale"):
        require_formal_api_gate(gate_path, precheck_path)


@pytest.mark.parametrize(
    ("tavily_remaining", "tavily_paygo", "message"),
    [
        (0, 0, "remaining"),
        (1, 1, "PAYG"),
    ],
)
def test_formal_api_gate_rejects_unusable_tavily_free_budget(
    tmp_path,
    tavily_remaining,
    tavily_paygo,
    message,
):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        tavily_remaining=tavily_remaining,
        tavily_paygo=tavily_paygo,
        billing_evidence={
            "source": "authenticated account console",
            "method": "account_level_check",
            "account_scope": "api_key_account",
            "evidence_ref": "test-evidence",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    with pytest.raises(FormalGateError, match=message):
        require_formal_api_gate(gate_path, precheck_path)


@pytest.mark.parametrize(
    ("gemini_updates", "message"),
    [
        ({"target_model_visible": False}, "target model"),
        ({"model": "different-model"}, "model mismatch"),
    ],
)
def test_formal_api_gate_rejects_unverified_target_model(
    tmp_path,
    gemini_updates,
    message,
):
    gate_path, precheck_path = _write_gate(
        tmp_path,
        gate_status="READY_FOR_PREFLIGHT",
        billing_boundary="FREE_CONFIRMED",
        billing_evidence={
            "source": "authenticated account console",
            "method": "account_level_check",
            "account_scope": "api_key_account",
            "evidence_ref": "test-evidence",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    precheck["gemini"].update(gemini_updates)
    precheck_path.write_text(json.dumps(precheck), encoding="utf-8")

    with pytest.raises(FormalGateError, match=message):
        require_formal_api_gate(gate_path, precheck_path)


def test_frozen_ground_truth_gate_rejects_manifest_hash_drift(tmp_path):
    source = tmp_path / "ground_truth.jsonl"
    manifest = tmp_path / "ground_truth_manifest.json"
    claim = GroundTruthClaim(
        claim_id="claim-1",
        claim="地区 GDP 为 1 亿元",
        source="官方统计公报",
        url="https://example.gov.cn/statistics",
        date="2026-01-01",
        region="测试县",
        metric="GDP",
        unit="亿元",
        evidence_excerpt="地区 GDP 为 1 亿元",
        confidence="high",
        verification_status="VERIFIED",
        verification_sources=("source-a", "source-b"),
        verification_contexts=("context-a", "context-b"),
    )
    GroundTruthStore.write(source, [claim])
    manifest.write_text(
        json.dumps(
            {
                "status": "FROZEN_FORMAL_MINIMUM_TARGET",
                "formal_ground_truth": True,
                "source_hash": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FormalGateError, match="ground truth manifest hash mismatch"):
        require_frozen_ground_truth(source, manifest)


def test_frozen_launch_manifest_rejects_file_hash_drift(tmp_path):
    shared = tmp_path / "shared.json"
    shared.write_text("frozen", encoding="utf-8")
    actual_hash = hashlib.sha256(b"frozen").hexdigest()
    launch = tmp_path / "launch.json"
    launch.write_text(
        json.dumps(
            {
                "status": "FROZEN_LAUNCH_CONFIGURATION",
                "model": "gemini-3.1-flash-lite",
                "search_provider": "tavily",
                "frozen_inputs": {
                    key: {
                        "path": "shared.json",
                        "sha256": "0" * 64 if key == "protocol" else actual_hash,
                    }
                    for key in (
                        "protocol",
                        "rubric",
                        "formal_regions",
                        "ground_truth_manifest",
                        "fixed_input_manifest",
                    )
                } | {
                    "fixed_input_packs": [
                        {
                            "file": "shared.json",
                            "source_hash": "1" * 64,
                            "file_sha256": actual_hash,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FormalGateError, match="launch manifest hash mismatch"):
        require_frozen_launch_manifest(
            launch,
            expected_model="gemini-3.1-flash-lite",
            expected_search_provider="tavily",
        )


def test_frozen_launch_manifest_binds_llm_provider_when_gate_declares_one(tmp_path):
    shared = tmp_path / "shared.json"
    shared.write_text("frozen", encoding="utf-8")
    actual_hash = hashlib.sha256(b"frozen").hexdigest()
    launch = tmp_path / "launch.json"
    launch.write_text(
        json.dumps(
            {
                "status": "FROZEN_LAUNCH_CONFIGURATION",
                "llm_provider": "gemini",
                "model": "deepseek-chat",
                "search_provider": "deepseek",
                "frozen_inputs": {
                    key: {"path": "shared.json", "sha256": actual_hash}
                    for key in (
                        "protocol",
                        "rubric",
                        "formal_regions",
                        "ground_truth_manifest",
                        "fixed_input_manifest",
                    )
                }
                | {
                    "fixed_input_packs": [
                        {
                            "file": "shared.json",
                            "source_hash": "1" * 64,
                            "file_sha256": actual_hash,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FormalGateError, match="llm provider mismatch"):
        require_frozen_launch_manifest(
            launch,
            expected_model="deepseek-chat",
            expected_search_provider="deepseek",
            expected_llm_provider="deepseek",
        )
