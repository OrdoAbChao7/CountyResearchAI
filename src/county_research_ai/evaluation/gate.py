"""Formal experiment gates for account billing and resource prechecks."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FormalGateError(RuntimeError):
    """Formal API execution is not authorized by the persisted gate."""


DEFAULT_PRECHECK_MAX_AGE_SECONDS = 24 * 60 * 60
DEEPSEEK_ALLOWED_BILLING_BOUNDARIES = {
    "FREE_CONFIRMED",
    "USER_AUTHORIZED_PAID",
}


def require_ground_truth_collection_gate(
    gate_path: Path,
    precheck_path: Path | None = None,
    *,
    max_precheck_age_seconds: int = DEFAULT_PRECHECK_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Authorize only the current, explicitly scoped Ground Truth collection.

    This is intentionally separate from ``require_formal_api_gate``.  A current
    user authorization to make paid calls can unlock source collection for this
    task, but it must not silently reopen historical E1/E2 launch manifests or
    reinterpret old billing evidence as account-level confirmation.
    """
    gate_file = Path(gate_path)
    gate = _load_json(gate_file)
    configured = gate.get("resource_precheck")
    if precheck_path is None:
        if not configured:
            raise FormalGateError("ground truth gate has no resource precheck")
        precheck_path = gate_file.parent / str(configured)
    precheck = _load_json(Path(precheck_path))

    if gate.get("status") != "READY_FOR_GROUND_TRUTH":
        raise FormalGateError(
            "ground truth collection gate is not open: "
            f"status={gate.get('status', '<missing>')}"
        )
    if gate.get("business_api_calls_allowed") is not True:
        raise FormalGateError("ground truth collection business calls are disabled")
    if gate.get("allow_paid_authorized") is not True:
        raise FormalGateError("ground truth collection paid authorization is missing")
    scope = gate.get("scope")
    if not isinstance(scope, list) or set(scope) != {"ground_truth_collection"}:
        raise FormalGateError("ground truth gate scope must be ground_truth_collection only")
    if str(gate.get("llm_provider", "")).lower() != "deepseek":
        raise FormalGateError("ground truth collection LLM provider must be deepseek")
    if str(gate.get("search_provider", "")).lower() != "deepseek":
        raise FormalGateError("ground truth collection search provider must be deepseek")
    model = gate.get("model")
    if not isinstance(model, str) or not model.strip():
        raise FormalGateError("ground truth collection model is missing")

    _validate_precheck_freshness(
        precheck,
        max_precheck_age_seconds=max_precheck_age_seconds,
    )
    _validate_current_user_authorization(
        gate.get("authorization"),
        max_precheck_age_seconds=max_precheck_age_seconds,
    )
    deepseek = precheck.get("deepseek")
    if not isinstance(deepseek, dict) or deepseek.get("provider") != "deepseek":
        raise FormalGateError("Ground Truth DeepSeek precheck is missing or invalid")
    if deepseek.get("model") != model:
        raise FormalGateError(
            "Ground Truth DeepSeek model mismatch: "
            f"gate={model}, precheck={deepseek.get('model') or '<missing>'}"
        )
    if deepseek.get("llm_configured") is not True:
        raise FormalGateError("DeepSeek LLM is not configured")
    if deepseek.get("search_configured") is not True:
        raise FormalGateError("DeepSeek Search/Fetch is not configured")
    if deepseek.get("search_enabled") is not True:
        raise FormalGateError("DeepSeek Search/Fetch is not enabled")
    return {"gate": gate, "precheck": precheck}


def require_formal_api_gate(
    gate_path: Path,
    precheck_path: Path | None = None,
    *,
    max_precheck_age_seconds: int = DEFAULT_PRECHECK_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Require an explicitly opened free-resource gate before business API calls."""
    gate_file = Path(gate_path)
    gate = _load_json(gate_file)
    if precheck_path is None:
        configured = gate.get("resource_precheck")
        if not configured:
            raise FormalGateError("formal gate has no resource precheck")
        precheck_path = gate_file.parent / str(configured)
    precheck = _load_json(Path(precheck_path))

    if gate.get("status") not in {"READY_FOR_PREFLIGHT", "READY_FOR_FORMAL_RUN"}:
        raise FormalGateError(
            f"formal API gate is not open: status={gate.get('status', '<missing>')}"
        )
    configured_launch = gate.get("launch_manifest")
    if configured_launch:
        launch_path = _resolve_reference(gate_file, str(configured_launch))
        require_frozen_launch_manifest(
            launch_path,
            expected_model=gate.get("model"),
            expected_search_provider=gate.get("search_provider"),
            expected_llm_provider=gate.get("llm_provider"),
        )
    authorization_reference = gate.get("authorization_manifest")
    if authorization_reference:
        authorization_path = _resolve_reference(gate_file, str(authorization_reference))
        _validate_free_only_authorization(
            _load_json(authorization_path),
            max_precheck_age_seconds=max_precheck_age_seconds,
        )
    paid_authorization_reference = gate.get("paid_authorization_manifest")
    if paid_authorization_reference:
        paid_authorization_path = _resolve_reference(
            gate_file, str(paid_authorization_reference)
        )
        _validate_paid_authorization(
            _load_json(paid_authorization_path),
            max_precheck_age_seconds=max_precheck_age_seconds,
        )
    _validate_precheck_freshness(
        precheck,
        max_precheck_age_seconds=max_precheck_age_seconds,
    )
    llm_provider = str(gate.get("llm_provider", "gemini")).lower()
    if llm_provider == "deepseek":
        _validate_deepseek_llm_precheck(
            gate,
            precheck,
            max_precheck_age_seconds=max_precheck_age_seconds,
        )
    else:
        _validate_gemini_precheck(
            gate,
            precheck,
            max_precheck_age_seconds=max_precheck_age_seconds,
        )

    search_provider = str(gate.get("search_provider", "tavily")).lower()
    if search_provider == "deepseek":
        _validate_deepseek_search_precheck(
            precheck,
            max_precheck_age_seconds=max_precheck_age_seconds,
        )
    else:
        _validate_tavily_precheck(precheck)
    return {"gate": gate, "precheck": precheck}


def require_frozen_launch_manifest(
    launch_path: Path,
    *,
    expected_model: Any,
    expected_search_provider: Any,
    expected_llm_provider: Any = None,
) -> dict[str, Any]:
    """Verify the frozen launch configuration and all referenced file hashes."""
    launch_file = Path(launch_path)
    launch = _load_json(launch_file)
    if launch.get("status") != "FROZEN_LAUNCH_CONFIGURATION":
        raise FormalGateError("formal launch manifest is not frozen")
    if launch.get("model") != expected_model:
        raise FormalGateError(
            "formal launch manifest model mismatch: "
            f"expected={expected_model}, actual={launch.get('model')}"
        )
    if launch.get("search_provider") != expected_search_provider:
        raise FormalGateError(
            "formal launch manifest search provider mismatch: "
            f"expected={expected_search_provider}, actual={launch.get('search_provider')}"
        )
    if expected_llm_provider is not None:
        actual_llm_provider = launch.get("llm_provider", "gemini")
        if actual_llm_provider != expected_llm_provider:
            raise FormalGateError(
                "formal launch manifest llm provider mismatch: "
                f"expected={expected_llm_provider}, actual={actual_llm_provider}"
            )
    frozen_inputs = launch.get("frozen_inputs")
    if not isinstance(frozen_inputs, dict):
        raise FormalGateError("formal launch manifest has no frozen inputs")
    for key in (
        "protocol",
        "rubric",
        "formal_regions",
        "ground_truth_manifest",
        "fixed_input_manifest",
    ):
        reference = frozen_inputs.get(key)
        if not isinstance(reference, dict):
            raise FormalGateError(f"formal launch manifest missing input: {key}")
        _verify_file_hash_reference(launch_file, reference, label=key)
    packs = frozen_inputs.get("fixed_input_packs")
    if not isinstance(packs, list) or not packs:
        raise FormalGateError("formal launch manifest has no fixed-input packs")
    fixed_manifest = frozen_inputs["fixed_input_manifest"]
    fixed_manifest_path = _resolve_reference(launch_file, str(fixed_manifest["path"]))
    for index, entry in enumerate(packs):
        if not isinstance(entry, dict):
            raise FormalGateError(f"formal launch pack entry is invalid: {index}")
        source_hash = entry.get("source_hash")
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise FormalGateError(f"formal launch pack source hash is invalid: {index}")
        file_name = entry.get("file")
        file_sha256 = entry.get("file_sha256")
        if not isinstance(file_name, str) or not isinstance(file_sha256, str):
            raise FormalGateError(f"formal launch pack file hash is missing: {index}")
        _verify_digest(
            fixed_manifest_path.parent / file_name,
            file_sha256,
            label=f"fixed_input_packs[{index}]",
        )
    return launch


def _verify_file_hash_reference(
    launch_file: Path,
    reference: dict[str, Any],
    *,
    label: str,
) -> None:
    raw_path = reference.get("path")
    expected_hash = reference.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
        raise FormalGateError(f"formal launch manifest hash reference is invalid: {label}")
    _verify_digest(
        _resolve_reference(launch_file, raw_path),
        expected_hash,
        label=label,
    )


def _verify_digest(path: Path, expected_hash: str, *, label: str) -> None:
    try:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FormalGateError(f"cannot read formal launch input: {path}") from exc
    if actual_hash != expected_hash.lower():
        raise FormalGateError(
            f"formal launch manifest hash mismatch: {label} ({path})"
        )


def _resolve_reference(base_file: Path, raw_path: str) -> Path:
    reference = Path(raw_path)
    if reference.is_absolute():
        return reference
    candidates = (
        base_file.parent / reference,
        Path(__file__).resolve().parents[3] / reference,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _validate_precheck_freshness(
    precheck: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    checked_at = precheck.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at.strip():
        raise FormalGateError("resource precheck timestamp is missing")
    try:
        checked_datetime = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FormalGateError("resource precheck timestamp is invalid") from exc
    if checked_datetime.tzinfo is None:
        raise FormalGateError("resource precheck timestamp must include timezone")
    age_seconds = (
        datetime.now(timezone.utc) - checked_datetime.astimezone(timezone.utc)
    ).total_seconds()
    if age_seconds > max_precheck_age_seconds:
        raise FormalGateError(
            "resource precheck is stale: "
            f"age_seconds={age_seconds:.0f}, max={max_precheck_age_seconds}"
        )


def _validate_gemini_precheck(
    gate: dict[str, Any],
    precheck: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    gemini = precheck.get("gemini")
    expected_model = gate.get("model")
    if not isinstance(gemini, dict):
        raise FormalGateError("Gemini resource precheck is missing")
    if gemini.get("provider") != "gemini":
        raise FormalGateError("Gemini resource precheck provider is invalid")
    if not isinstance(expected_model, str) or not expected_model.strip():
        raise FormalGateError("formal gate model is missing")
    if gemini.get("model") != expected_model:
        raise FormalGateError(
            "Gemini model mismatch: "
            f"gate={expected_model}, precheck={gemini.get('model') or '<missing>'}"
        )
    if (
        gemini.get("models_list_http_status") != 200
        or gemini.get("target_model_visible") is not True
    ):
        if gemini.get("model_validation") != "LIVE_CALL_REQUIRED":
            raise FormalGateError(
                "Gemini target model visibility is not verified: "
                f"model={gemini.get('model') or '<missing>'}"
            )
    billing_boundary = gemini.get("billing_boundary")
    if billing_boundary != "FREE_CONFIRMED":
        raise FormalGateError(
            "Gemini account billing boundary is not FREE_CONFIRMED: "
            f"{billing_boundary or '<missing>'}"
        )
    billing_evidence = gemini.get("billing_evidence")
    _validate_billing_evidence(
        billing_evidence,
        label="Gemini",
        max_precheck_age_seconds=max_precheck_age_seconds,
    )


def _validate_deepseek_llm_precheck(
    gate: dict[str, Any],
    precheck: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    deepseek = _require_deepseek_precheck(precheck)
    expected_model = gate.get("model")
    if deepseek.get("model") != expected_model:
        raise FormalGateError(
            "DeepSeek model mismatch: "
            f"gate={expected_model or '<missing>'}, "
            f"precheck={deepseek.get('model') or '<missing>'}"
        )
    if deepseek.get("configured") is not True:
        raise FormalGateError("DeepSeek LLM is not configured")
    allowed_boundaries = {"FREE_CONFIRMED"}
    if gate.get("paid_authorization_manifest"):
        allowed_boundaries = DEEPSEEK_ALLOWED_BILLING_BOUNDARIES
    if deepseek.get("llm_billing_boundary") not in allowed_boundaries:
        raise FormalGateError(
            "DeepSeek LLM billing boundary is not allowed: "
            f"{deepseek.get('llm_billing_boundary') or '<missing>'}"
        )
    _validate_billing_evidence(
        deepseek.get("llm_billing_evidence"),
        label="DeepSeek LLM",
        max_precheck_age_seconds=max_precheck_age_seconds,
    )


def _validate_deepseek_search_precheck(
    precheck: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    deepseek = _require_deepseek_precheck(precheck)
    if deepseek.get("configured") is not True or deepseek.get("enabled") is not True:
        raise FormalGateError(
            "DeepSeek Search/Fetch is not explicitly enabled for the formal gate"
        )
    if (
        deepseek.get("search_fetch_billing_boundary")
        not in DEEPSEEK_ALLOWED_BILLING_BOUNDARIES
    ):
        raise FormalGateError(
            "DeepSeek Search/Fetch billing boundary is not allowed: "
            f"{deepseek.get('search_fetch_billing_boundary') or '<missing>'}"
        )
    _validate_billing_evidence(
        deepseek.get("search_fetch_billing_evidence"),
        label="DeepSeek Search/Fetch",
        max_precheck_age_seconds=max_precheck_age_seconds,
    )


def _require_deepseek_precheck(precheck: dict[str, Any]) -> dict[str, Any]:
    deepseek = precheck.get("deepseek")
    if not isinstance(deepseek, dict) or deepseek.get("provider") != "deepseek":
        raise FormalGateError("DeepSeek resource precheck is missing or invalid")
    return deepseek


def _validate_billing_evidence(
    billing_evidence: Any,
    *,
    label: str,
    max_precheck_age_seconds: int,
) -> None:
    required_evidence_fields = (
        "source",
        "method",
        "account_scope",
        "evidence_ref",
        "verified_at",
    )
    if not isinstance(billing_evidence, dict) or any(
        not isinstance(billing_evidence.get(field), str)
        or not billing_evidence[field].strip()
        for field in required_evidence_fields
    ):
        raise FormalGateError(
            f"{label} billing boundary requires auditable billing evidence"
        )
    try:
        evidence_datetime = datetime.fromisoformat(
            billing_evidence["verified_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FormalGateError(f"{label} billing evidence timestamp is invalid") from exc
    if evidence_datetime.tzinfo is None:
        raise FormalGateError(
            f"{label} billing evidence timestamp must include timezone"
        )
    evidence_age_seconds = (
        datetime.now(timezone.utc)
        - evidence_datetime.astimezone(timezone.utc)
    ).total_seconds()
    if evidence_age_seconds > max_precheck_age_seconds:
        raise FormalGateError(
            f"{label} billing evidence is stale: "
            f"age_seconds={evidence_age_seconds:.0f}, max={max_precheck_age_seconds}"
        )


def _validate_free_only_authorization(
    authorization: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    if authorization.get("status") != "ACTIVE_FREE_ONLY":
        raise FormalGateError("free-only resource authorization is not active")
    evidence = authorization.get("authorization")
    _validate_billing_evidence(
        evidence,
        label="free-only user authorization",
        max_precheck_age_seconds=max_precheck_age_seconds,
    )
    providers = authorization.get("providers")
    if not isinstance(providers, dict):
        raise FormalGateError("free-only resource authorization has no providers")
    for provider in ("gemini", "tavily"):
        entry = providers.get(provider)
        if not isinstance(entry, dict) or entry.get("provider") != provider:
            raise FormalGateError(f"free-only authorization is missing provider: {provider}")
        if entry.get("billing_boundary") != "FREE_CONFIRMED":
            raise FormalGateError(f"{provider} free billing boundary is not confirmed")
        if entry.get("free_only") is not True:
            raise FormalGateError(f"{provider} free-only flag is not true")
        if entry.get("paid_overage_allowed") is not False:
            raise FormalGateError(f"{provider} paid_overage_allowed must be false")
        if entry.get("auto_switch_paid") is not False:
            raise FormalGateError(f"{provider} auto_switch_paid must be false")


def _validate_paid_authorization(
    authorization: dict[str, Any],
    *,
    max_precheck_age_seconds: int,
) -> None:
    if authorization.get("status") != "ACTIVE_USER_AUTHORIZED_PAID":
        raise FormalGateError("paid resource authorization is not active")
    evidence = authorization.get("authorization")
    _validate_billing_evidence(
        evidence,
        label="paid user authorization",
        max_precheck_age_seconds=max_precheck_age_seconds,
    )
    providers = authorization.get("providers")
    if not isinstance(providers, dict):
        raise FormalGateError("paid resource authorization has no providers")
    entry = providers.get("deepseek_llm")
    if not isinstance(entry, dict) or entry.get("provider") != "deepseek":
        raise FormalGateError("paid authorization is missing DeepSeek LLM provider")
    if entry.get("scope") != "llm":
        raise FormalGateError("paid authorization scope must be DeepSeek LLM only")
    if entry.get("billing_boundary") != "USER_AUTHORIZED_PAID":
        raise FormalGateError("DeepSeek LLM paid billing boundary is not authorized")
    if entry.get("paid_overage_allowed") is not True:
        raise FormalGateError("DeepSeek LLM paid_overage_allowed must be true")
    if entry.get("auto_switch_paid") is not False:
        raise FormalGateError("DeepSeek LLM auto_switch_paid must be false")


def _validate_current_user_authorization(
    authorization: Any,
    *,
    max_precheck_age_seconds: int,
) -> None:
    """Validate a fresh, task-scoped user authorization without inventing prices."""
    required_fields = (
        "source",
        "method",
        "account_scope",
        "evidence_ref",
        "verified_at",
    )
    if not isinstance(authorization, dict) or any(
        not isinstance(authorization.get(field), str)
        or not authorization[field].strip()
        for field in required_fields
    ):
        raise FormalGateError("current user authorization evidence is missing")
    if authorization["method"] != "explicit_current_user_authorization":
        raise FormalGateError("ground truth gate requires explicit current user authorization")
    if authorization["account_scope"] != "current_task":
        raise FormalGateError("ground truth authorization scope is not current_task")
    try:
        verified_at = datetime.fromisoformat(
            authorization["verified_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FormalGateError("current user authorization timestamp is invalid") from exc
    if verified_at.tzinfo is None:
        raise FormalGateError("current user authorization timestamp must include timezone")
    age_seconds = (
        datetime.now(timezone.utc) - verified_at.astimezone(timezone.utc)
    ).total_seconds()
    if age_seconds > max_precheck_age_seconds:
        raise FormalGateError(
            "current user authorization is stale: "
            f"age_seconds={age_seconds:.0f}, max={max_precheck_age_seconds}"
        )


def _validate_tavily_precheck(precheck: dict[str, Any]) -> None:
    tavily = precheck.get("tavily")
    if not isinstance(tavily, dict):
        raise FormalGateError("Tavily resource precheck is missing")
    tavily_status = tavily.get("status")
    if tavily_status != "FREE_PLAN_USAGE_VISIBLE":
        raise FormalGateError(
            "Tavily usage status is not free-plan visible: "
            f"{tavily_status or '<missing>'}"
        )
    remaining_credits = tavily.get("conservative_remaining_credits")
    if (
        not isinstance(remaining_credits, (int, float))
        or isinstance(remaining_credits, bool)
        or remaining_credits <= 0
    ):
        raise FormalGateError(
            "Tavily remaining free credits are missing or exhausted: "
            f"{remaining_credits!r}"
        )
    paygo_usage = tavily.get("paygo_usage_credits")
    if (
        not isinstance(paygo_usage, (int, float))
        or isinstance(paygo_usage, bool)
        or paygo_usage != 0
    ):
        raise FormalGateError(
            "Tavily PAYG usage is not zero: "
            f"{paygo_usage!r}"
        )


def require_frozen_ground_truth(
    ground_truth_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Verify formal Ground Truth integrity before any business API call."""
    from .ground_truth import GroundTruthStore

    try:
        bundle = GroundTruthStore.freeze_verified(
            Path(ground_truth_path),
            Path(manifest_path),
            require_cross_verification=True,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise FormalGateError(
            f"formal ground truth integrity check failed: {exc}"
        ) from exc
    return {"claim_count": len(bundle.claims), "source_hash": bundle.source_hash}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalGateError(f"cannot read formal gate file: {path}") from exc
    if not isinstance(value, dict):
        raise FormalGateError(f"formal gate file must contain an object: {path}")
    return value
