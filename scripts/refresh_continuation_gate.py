"""Refresh the continuation free-only gate after provider configuration changes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.precheck_independent_resources import (
    DEFAULT_AUTHORIZATION_PATH,
    build_precheck,
)

from county_research_ai.config import load_settings

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
DEFAULT_PRECHECK_PATH = FORMAL_ROOT / "manifests" / "resource_precheck_20261019.json"
DEFAULT_GATE_PATH = FORMAL_ROOT / "manifests" / "continuation_resource_gate_20261018.json"


def refresh_gate(
    *,
    authorization_path: Path = DEFAULT_AUTHORIZATION_PATH,
    precheck_path: Path = DEFAULT_PRECHECK_PATH,
    gate_path: Path = DEFAULT_GATE_PATH,
) -> dict[str, Any]:
    authorization = json.loads(Path(authorization_path).read_text(encoding="utf-8"))
    precheck = build_precheck(settings=load_settings(), authorization=authorization)
    precheck_path.parent.mkdir(parents=True, exist_ok=True)
    precheck_path.write_text(json.dumps(precheck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gate = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    gemini = precheck.get("gemini", {})
    tavily = precheck.get("tavily", {})
    model_visible = (
        gemini.get("models_list_http_status") == 200
        and gemini.get("target_model_visible") is True
    )
    tavily_free = (
        tavily.get("status") == "FREE_PLAN_USAGE_VISIBLE"
        and isinstance(tavily.get("conservative_remaining_credits"), (int, float))
        and tavily.get("conservative_remaining_credits") > 0
        and tavily.get("paygo_usage_credits") == 0
    )
    authorization_active = authorization.get("status") == "ACTIVE_FREE_ONLY"
    if model_visible and tavily_free and authorization_active:
        gate.update(
            {
                "status": "READY_FOR_PREFLIGHT",
                "business_api_calls_allowed": True,
                "blocked_providers": [],
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "reason": "Fresh free-only precheck passed for Gemini and Tavily.",
            }
        )
        result_status = "READY_FOR_PREFLIGHT"
    else:
        blocked_providers = []
        if not model_visible:
            blocked_providers.append("gemini")
        if not tavily_free:
            blocked_providers.append("tavily")
        if not authorization_active:
            blocked_providers.append("authorization")
        gate.update(
            {
                "status": "BLOCKED_PROVIDER_CONFIGURATION",
                "business_api_calls_allowed": False,
                "blocked_providers": blocked_providers,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "reason": "Fresh free-only precheck did not verify all required Provider conditions.",
            }
        )
        result_status = "BLOCKED_PROVIDER_CONFIGURATION"
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": result_status,
        "precheck": str(precheck_path),
        "gate": str(gate_path),
        "gemini_model_visible": model_visible,
        "tavily_free": tavily_free,
        "authorization_active": authorization_active,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path, default=DEFAULT_AUTHORIZATION_PATH)
    parser.add_argument("--precheck", type=Path, default=DEFAULT_PRECHECK_PATH)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE_PATH)
    args = parser.parse_args()
    print(json.dumps(refresh_gate(
        authorization_path=args.authorization,
        precheck_path=args.precheck,
        gate_path=args.gate,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
