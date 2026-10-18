"""从独立实验 Manifest 生成状态报告；不把无效运行纳入质量指标。"""
from __future__ import annotations

import argparse
from pathlib import Path

from county_research_ai.evaluation.reporting import load_manifests, render_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifests = load_manifests(args.runs_root)
    report = render_markdown_report(
        title="CountyResearchAI Independent Comparison Status",
        manifests=manifests,
        quality_conclusion="INCONCLUSIVE",
        notes=[
            "This file is a reproducible status report, not a claim that the formal comparison passed.",
            "Only VALID runs may enter future claim-level metrics; BLOCKED, FAILED and INVALID runs remain in the ledger.",
            "Ground Truth, independent judges and formal statistical comparison are required before a performance conclusion.",
            "The 于都县 pilot has no valid A/B/C triplet: A/B were invalidated for resource overrun and C was blocked.",
            "The six-region minimum Ground Truth and formal fixed-input manifest are frozen; the formal target gate remains NOT_RUN until account quota/billing checks and a bounded preflight are complete.",
            "E2 fixed-input runners are implemented but no formal fixed-input API batch has been executed.",
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
