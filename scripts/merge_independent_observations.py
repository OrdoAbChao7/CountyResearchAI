"""合并 Claim、Blind Judge 和 Report-Based QA 的可重算 observation。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"observation must be an object at {path}:{line_number}")
        rows.append(value)
    return rows


def merge_observations(
    claims_path: Path,
    judgements_path: Path | None,
    qa_path: Path | None,
    output_path: Path,
) -> dict[str, int]:
    claim_rows = _load_jsonl(claims_path)
    judge_by_run = {str(row["run_id"]): row for row in _load_jsonl(judgements_path) if "run_id" in row}
    qa_by_run = {str(row["run_id"]): row for row in _load_jsonl(qa_path) if "run_id" in row}
    merged: list[dict[str, Any]] = []
    for input_row in claim_rows:
        row = dict(input_row)
        metrics = dict(row.get("metrics") or {})
        run_id = str(row.get("run_id", ""))
        judge = judge_by_run.get(run_id)
        qa = qa_by_run.get(run_id)
        if (
            judge is not None
            and judge.get("status") == "VALID"
            and isinstance(judge.get("analysis_depth"), (int, float))
        ):
            metrics["analysis_depth"] = float(judge["analysis_depth"])
            row["judge_status"] = "VALID"
        if (
            qa is not None
            and qa.get("status") == "VALID"
            and isinstance(qa.get("qa_accuracy"), (int, float))
        ):
            metrics["report_qa_accuracy"] = float(qa["qa_accuracy"])
            row["qa_status"] = "VALID"
        row["metrics"] = metrics
        merged.append(row)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in merged),
        encoding="utf-8",
    )
    return {
        "rows": len(merged),
        "valid_rows": sum(1 for row in merged if row.get("status") == "VALID"),
        "rows_with_judge": sum(1 for row in merged if row.get("judge_status") == "VALID"),
        "rows_with_qa": sum(1 for row in merged if row.get("qa_status") == "VALID"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--judgements", type=Path)
    parser.add_argument("--qa", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            merge_observations(args.claims, args.judgements, args.qa, args.output),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
