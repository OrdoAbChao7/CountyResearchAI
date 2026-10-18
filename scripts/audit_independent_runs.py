"""审计独立实验 Manifest、产物哈希和资源租约。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from county_research_ai.evaluation.auditing import audit_runs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    report = audit_runs(args.runs_root)
    payload = {
        "runs_checked": report.runs_checked,
        "passed": report.passed,
        "issues": [issue.__dict__ for issue in report.issues],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
