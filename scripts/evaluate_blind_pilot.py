"""Locked blind-pilot evaluation: A/B/C reports vs deterministic Strategy D.

Two disjoint tasks (安吉县, 信丰县) and 10 manually verified facts. A/B reports
exist only for 安吉县; missing groups are reported as NOT_RUN, never imputed.
No provider or judge calls.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.diagnose_quality_funnel import answer_present
from scripts.evaluate_adaptive_retrieval_offline import load_docs
from scripts.evaluate_strategy_d_offline import task_window

from county_research_ai.application.verified_answer import build_verified_answer
from county_research_ai.evidence.graph import EvidenceGraphStore
from county_research_ai.evidence.ledger import build_evidence_ledger
from county_research_ai.models import CountyInfo
from county_research_ai.processor import DocumentProcessor

ROOT = Path(__file__).resolve().parents[1]
BLIND = ROOT / "experiments/quality/dataset/blind_pilot.jsonl"
SMOKE = ROOT / "experiments/independent_comparison/runs/smoke_20261018T095509Z"
OUTPUT = ROOT / "experiments/quality/20261026_q4_blind_pilot"


def report_path(region: str, group: str) -> Path | None:
    run_dir = SMOKE / f"smoke_20261018T095509Z_{region}_{group}"
    direct = run_dir / "report.md"
    if direct.is_file():
        return direct
    generated = sorted((run_dir / "generated_reports").glob("*.md"))
    return generated[0] if generated else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    facts = [
        json.loads(line)
        for line in BLIND.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        tasks[fact["task_id"]].append(fact)
    rows: list[dict[str, Any]] = []
    import tempfile

    with tempfile.TemporaryDirectory(prefix="q4-blind-") as tmp:
        graph = EvidenceGraphStore(Path(tmp) / "graph.sqlite")
        for task_id, task_facts in sorted(tasks.items()):
            region = task_facts[0]["region"]
            snapshot = ROOT / task_facts[0]["snapshot_path"]
            docs = load_docs(snapshot)
            processed = DocumentProcessor().process(
                docs,
                county=CountyInfo.from_name(region),
                focus=task_facts[0].get("metric", ""),
            )
            ledger = build_evidence_ledger(processed)
            window = task_window(
                [
                    type(
                        "Fact",
                        (),
                        {
                            "metric_year": str(fact["period"]),
                        },
                    )()
                    for fact in task_facts
                ]
            )
            run_id = f"blind:{task_id}"
            graph.save_ledger(ledger, run_id=run_id, window=window)
            d_answer = build_verified_answer(graph, run_id)
            reports = {
                group: (path.read_text(encoding="utf-8") if path else "")
                for group in ("A", "B", "C")
                for path in [report_path(region, group)]
            }
            for fact in task_facts:
                answer_hits = {
                    group: answer_present(
                        type(
                            "GT",
                            (),
                            {
                                "expected_answer": fact["expected_answer"],
                                "claim": fact["expected_answer"],
                                "unit": fact["unit"],
                                "metric": fact["metric"],
                            },
                        )(),
                        text,
                    )["present"]
                    for group, text in reports.items()
                }
                d_hit = answer_present(
                    type(
                        "GT",
                        (),
                        {
                            "expected_answer": fact["expected_answer"],
                            "claim": fact["expected_answer"],
                            "unit": fact["unit"],
                            "metric": fact["metric"],
                        },
                    )(),
                    d_answer["text"],
                )["present"]
                rows.append(
                    {
                        "task_id": task_id,
                        "region": region,
                        "fact_id": fact["fact_id"],
                        "metric": fact["metric"],
                        "value": fact["value"],
                        "unit": fact["unit"],
                        "period": fact["period"],
                        "A_answered": answer_hits.get("A", False),
                        "B_answered": answer_hits.get("B", False),
                        "C_answered": answer_hits.get("C", False),
                        "D_answered": d_hit,
                        "D_supported": any(
                            item["value"] == fact["value"]
                            and item["unit"] == fact["unit"]
                            for item in d_answer["supported_claims"]
                        ),
                    }
                )
    groups = ("A", "B", "C", "D")
    regions = sorted({row["region"] for row in rows})
    summary = {}
    for group in groups:
        available_regions = (
            regions
            if group == "D"
            else [region for region in regions if report_path(region, group) is not None]
        )
        available_facts = sum(
            1 for row in rows if row["region"] in available_regions
        )
        answered = sum(
            1
            for row in rows
            if row["region"] in available_regions and row[f"{group}_answered"]
        )
        summary[group] = {
            "answered": answered,
            "facts": available_facts,
            "answer_rate": round(answered / available_facts, 4)
            if available_facts
            else None,
            "regions_with_report": available_regions,
        }
    d_supported = sum(1 for row in rows if row["D_supported"])
    d_e2e = sum(1 for row in rows if row["D_supported"] and row["D_answered"])
    summary["D"]["supported"] = d_supported
    summary["D"]["e2e"] = d_e2e
    summary["D"]["e2e_rate"] = round(d_e2e / len(rows), 4)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "OFFLINE_BLIND_PILOT",
        "provider_calls": 0,
        "blind_file_sha256": __import__("hashlib").sha256(BLIND.read_bytes()).hexdigest(),
        "tasks": {
            task_id: {
                "region": items[0]["region"],
                "facts": len(items),
                "snapshot_path": items[0]["snapshot_path"],
            }
            for task_id, items in sorted(tasks.items())
        },
        "summary": summary,
        "rows": rows,
        "not_run": {
            "A/B for 信丰县": "no report archive for the smoke A/B runs",
            "40-60 task blind set": "only 2 disjoint archived tasks had verifiable exact quotes",
        },
        "caveats": [
            "Pilot only: 2 tasks / 10 facts; not a comprehensive blind benchmark.",
            "D is a deterministic extractive answer; A/B/C are archived reports.",
            "Answer coverage is not prose quality or citation precision.",
            "A/B reports exist only for 安吉县; missing groups are NOT_RUN, not zero-scored.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Blind pilot A/B/C/D",
        "",
        f"Generated: {report['generated_at']} · provider calls 0",
        "",
        "| Group | Answered | Facts | Answer rate | Regions |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for group in groups:
        item = summary[group]
        rate = (
            f"{item['answer_rate']:.1%}"
            if item["answer_rate"] is not None
            else "NOT_RUN"
        )
        lines.append(
            f"| {group} | {item['answered']} | {item['facts']} | "
            f"{rate} | {', '.join(item['regions_with_report']) or 'none'} |"
        )
    lines += [
        "",
        f"- D supported: {d_supported}/{len(rows)}",
        f"- D end-to-end (supported + answered): {d_e2e}/{len(rows)} ({summary['D']['e2e_rate']:.1%})",
        "",
        "## NOT_RUN",
        "",
    ]
    lines += [f"- {key}: {value}" for key, value in report["not_run"].items()]
    lines += ["", "## Caveats", ""]
    lines += [f"- {caveat}" for caveat in report["caveats"]]
    lines.append("")
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {args.output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
