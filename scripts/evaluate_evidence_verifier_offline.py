"""Offline verifier ablation on frozen C raw archives.

For every archived CountyResearchAI (group C) run with raw documents, rebuild the
legacy processed data and evidence claims, then compare the legacy
`verification_status` with the deterministic AxiomScope v2 verifier.

This isolates the verifier: both sides see the same extracted claims and source
text. It is **not** an end-to-end quality comparison and must not be presented as
one. No provider or Judge calls are made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.evaluate_adaptive_retrieval_offline import load_docs

from county_research_ai.evidence.graph import EvidenceGraphStore, VerificationStatus
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo
from county_research_ai.processor import DocumentProcessor

RUNS_ROOT = Path(
    "experiments/independent_comparison/runs/"
    "continuation_matched_budget_deepseek_flash_20261019"
)
FOCUS_BY_MODE = {
    "snapshot": "特色产业",
    "rise-fall": "产业兴衰",
    "long-history": "长周期兴衰史",
}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def discover_cases(runs_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw_path in sorted(runs_root.glob("*_C/data/raw/*/*/raw_docs.json")):
        run_dir = raw_path.parents[4]
        run_id = run_dir.name
        stem = run_id[:-2] if run_id.endswith("_C") else run_id
        stem = stem.rsplit("_", 1)[0]
        mode = stem.rsplit("_", 1)[-1]
        region = raw_path.parents[1].name
        cases.append(
            {
                "run_id": run_id,
                "region": region,
                "mode": mode,
                "raw_docs": raw_path,
                "focus": FOCUS_BY_MODE.get(mode, "特色产业"),
            }
        )
    return cases


def summarize_case(
    case: dict[str, Any], graph: EvidenceGraphStore, ledger
) -> dict[str, Any]:
    legacy_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    downgraded: list[dict[str, str]] = []
    upgraded: list[dict[str, str]] = []
    objective_support_count = 0
    withheld_by_conflict = 0
    for claim in sorted(ledger.claims.values(), key=lambda item: item.claim_id):
        legacy_status = claim.verification_status or "unknown"
        legacy_counter[legacy_status] += 1
        objective_support = EvidenceGraphStore._ledger_objective_support(
            claim, ledger
        )
        objective_support_count += int(objective_support)
        stored = graph.get_claim(claim.claim_id)
        if stored is None:
            continue
        try:
            deterministic_status = VerificationStatus(
                stored.verification_status.upper()
            )
        except ValueError:
            deterministic_status = VerificationStatus.INSUFFICIENT
        status_counter[deterministic_status.value] += 1
        reason = stored.verification_reason or "none"
        reason_counter[reason] += 1
        if (
            objective_support
            and deterministic_status is VerificationStatus.NEEDS_REVIEW
            and reason == "conflicting_supported_evidence"
        ):
            withheld_by_conflict += 1
        legacy_verified = legacy_status == "verified"
        deterministic_supported = deterministic_status is VerificationStatus.SUPPORTED
        if legacy_verified and not deterministic_supported:
            downgraded.append(
                {
                    "claim_id": claim.claim_id,
                    "metric": claim.metric_id,
                    "value": f"{claim.value}{claim.unit}",
                    "reason": reason,
                }
            )
        if deterministic_supported and not legacy_verified:
            upgraded.append(
                {
                    "claim_id": claim.claim_id,
                    "metric": claim.metric_id,
                    "value": f"{claim.value}{claim.unit}",
                }
            )
    return {
        "run_id": case["run_id"],
        "region": case["region"],
        "mode": case["mode"],
        "raw_docs": str(case["raw_docs"]),
        "raw_docs_sha256": hashlib.sha256(case["raw_docs"].read_bytes()).hexdigest(),
        "documents": len(ledger.sources),
        "spans": len(ledger.chunks),
        "claims": len(ledger.claims),
        "legacy_statuses": dict(sorted(legacy_counter.items())),
        "deterministic_statuses": dict(sorted(status_counter.items())),
        "reasons": dict(sorted(reason_counter.items())),
        "objective_support_count": objective_support_count,
        "withheld_by_conflict": withheld_by_conflict,
        "downgraded_count": len(downgraded),
        "upgraded_count": len(upgraded),
        "downgraded": downgraded,
        "upgraded": upgraded,
    }


def build_report(runs_root: Path) -> dict[str, Any]:
    cases = discover_cases(runs_root)
    if not cases:
        raise SystemExit(f"no C raw archives found under {runs_root}")
    with tempfile.TemporaryDirectory(prefix="axiomscope-verifier-") as tmp:
        graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        rows = []
        for case in cases:
            docs = load_docs(case["raw_docs"])
            processed = DocumentProcessor().process(
                docs,
                county=CountyInfo.from_name(case["region"]),
                focus=case["focus"],
            )
            ledger = build_evidence_ledger(processed)
            graph.save_ledger(ledger, run_id=case["run_id"])
            rows.append(summarize_case(case, graph, ledger))
    totals = {
        "runs": len(rows),
        "documents": sum(row["documents"] for row in rows),
        "spans": sum(row["spans"] for row in rows),
        "claims": sum(row["claims"] for row in rows),
        "legacy_verified": sum(
            row["legacy_statuses"].get("verified", 0) for row in rows
        ),
        "deterministic_supported": sum(
            row["deterministic_statuses"].get("SUPPORTED", 0) for row in rows
        ),
        "objective_support": sum(row["objective_support_count"] for row in rows),
        "withheld_by_conflict": sum(row["withheld_by_conflict"] for row in rows),
        "downgraded": sum(row["downgraded_count"] for row in rows),
        "upgraded": sum(row["upgraded_count"] for row in rows),
    }
    reasons: Counter[str] = Counter()
    for row in rows:
        reasons.update(row["reasons"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_VERIFIER_ABLATION",
        "provider_calls": 0,
        "semantic_judge_calls": 0,
        "scope": (
            "Same extracted claims and raw text; compares legacy verification "
            "with the deterministic v2 verifier. Not an end-to-end quality result."
        ),
        "totals": totals,
        "reason_counts": dict(sorted(reasons.items())),
        "cases": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# Verifier ablation on frozen C archives",
        "",
        f"Generated: {report['generated_at']}",
        f"Evidence kind: `{report['evidence_kind']}` · provider calls: 0",
        "",
        f"> {report['scope']}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Runs | {totals['runs']} |",
        f"| Extracted claims | {totals['claims']} |",
        f"| Legacy `verified` | {totals['legacy_verified']} |",
        f"| Deterministic objective support (value/span checks) | {totals['objective_support']} |",
        f"| Deterministic `SUPPORTED` after conflict resolution | {totals['deterministic_supported']} |",
        f"| Withheld by a supported conflict (`NEEDS_REVIEW`) | {totals['withheld_by_conflict']} |",
        f"| Downgraded (legacy verified → not supported) | {totals['downgraded']} |",
        f"| Upgraded (legacy unverified → supported) | {totals['upgraded']} |",
        "",
        "## Reasons",
        "",
        "| Reason | Claims |",
        "| --- | ---: |",
    ]
    for reason, count in report["reason_counts"].items():
        lines.append(f"| `{reason}` | {count} |")
    lines += [
        "",
        "## Cases",
        "",
        "| Run | Claims | Legacy verified | Objective support | Supported | Withheld by conflict | Downgraded | Upgraded |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["cases"]:
        lines.append(
            f"| {row['run_id']} | {row['claims']} | "
            f"{row['legacy_statuses'].get('verified', 0)} | "
            f"{row['objective_support_count']} | "
            f"{row['deterministic_statuses'].get('SUPPORTED', 0)} | "
            f"{row['withheld_by_conflict']} | "
            f"{row['downgraded_count']} | {row['upgraded_count']} |"
        )
    lines += [
        "",
        "Caveats: only group C archives with raw documents are included. "
        "This measures verifier behavior, not report or retrieval quality. "
        "Legacy claim identity is coarse (many different statements share "
        "metric/period/scope), so the conflict layer withholds many claims as "
        "`NEEDS_REVIEW`; that is a data-quality finding about the legacy "
        "extractor, not evidence that the verifier is correct on every case.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/evaluation/20261026_verifier_ablation"),
    )
    args = parser.parse_args()
    report = build_report(args.runs_root)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "summary.json", report)
    (args.output / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    print(json.dumps(report["reason_counts"], ensure_ascii=False, indent=2))
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
