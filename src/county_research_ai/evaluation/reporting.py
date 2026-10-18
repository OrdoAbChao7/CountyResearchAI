"""Manifest 输入校验与可重算的 Markdown 报告骨架。"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .experiment_models import RunStatus


class ReportInputError(ValueError):
    """报告输入缺失、污染或哈希不一致。"""


def load_manifests(runs_root: Path) -> list[dict[str, Any]]:
    """按路径稳定加载所有 Manifest，不读取报告正文作为事实来源。"""
    root = Path(runs_root).resolve()
    if not root.exists():
        raise ReportInputError(f"runs root does not exist: {root}")
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.rglob("manifest.json")):
        if path.parent == root:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportInputError(f"cannot read manifest: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReportInputError(f"manifest must be an object: {path}")
        _validate_manifest_shape(value, path)
        value["_manifest_path"] = str(path)
        manifests.append(value)
    return manifests


def validate_manifest_artifacts(manifest: dict[str, Any], run_dir: Path) -> None:
    """校验 Manifest 声明的每个产物存在且 SHA-256 未漂移。"""
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ReportInputError(f"artifacts must be an object: {manifest.get('run_id')}")
    root = Path(run_dir).resolve()
    for name, declaration in artifacts.items():
        if not isinstance(declaration, str) or ":" not in declaration:
            raise ReportInputError(f"invalid artifact declaration for {name}")
        relative, expected = declaration.rsplit(":", 1)
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            raise ReportInputError(f"artifact escapes run directory: {relative}")
        if not path.is_file():
            raise ReportInputError(f"artifact missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ReportInputError(f"hash mismatch for {path}: expected {expected}, got {digest}")


def build_status_summary(manifests: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item["status"]) for item in manifests).items()))


def render_markdown_report(
    *,
    title: str,
    manifests: list[dict[str, Any]],
    quality_conclusion: str,
    notes: list[str],
) -> str:
    statuses = build_status_summary(manifests)
    lines = [
        f"# {title}",
        "",
        f"- Quality conclusion: `{quality_conclusion}`",
        f"- Runs observed: `{len(manifests)}`",
        "",
        "## Status summary",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{status}` | {count} |" for status, count in statuses.items())
    lines.extend(["", "## Run ledger", "", "| Run | Group | County | Status | Error |", "| --- | --- | --- | --- | --- |"])
    for item in manifests:
        error = str(item.get("error") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{item.get('run_id', '')}` | `{item.get('group', '')}` | "
            f"{item.get('county', '')} | `{item.get('status', '')}` | {error} |"
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in notes)
    lines.append("")
    return "\n".join(lines)


def write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """写出可供图表重算的指标明细；调用方应只传入 VALID 运行结果。"""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with output.open("w", encoding="utf-8", newline="") as stream:
        if not fields:
            stream.write("")
            return
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: str(item.get("run_id", ""))):
            writer.writerow({field: row.get(field, "") for field in fields})


def _validate_manifest_shape(value: dict[str, Any], path: Path) -> None:
    required = {"run_id", "group", "county", "status", "artifacts"}
    missing = sorted(required - value.keys())
    if missing:
        raise ReportInputError(f"manifest missing fields at {path}: {', '.join(missing)}")
    try:
        RunStatus(value["status"])
    except ValueError as exc:
        raise ReportInputError(f"unknown run status at {path}: {value['status']}") from exc
