"""运行 E2 固定输入 A/B/C 批次。

该入口只接受已落盘的 FixedInputPack；每个组在独立 Python 进程中运行，
并把同一个输入哈希写入 Manifest。实际执行仍需调用方确认 Provider 账户资源。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from county_research_ai.config import load_settings
from county_research_ai.evaluation.checkpoints import CheckpointStore
from county_research_ai.evaluation.experiment_models import RunStatus
from county_research_ai.evaluation.experiment_runner import ExperimentRunSpec
from county_research_ai.evaluation.fixed_input import FixedInputPack
from county_research_ai.evaluation.gate import (
    require_formal_api_gate,
    require_frozen_ground_truth,
)
from county_research_ai.evaluation.resource_manager import ResourceLimit, ResourceManager

FORMAL_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "independent_comparison"
FORMAL_GATE_PATH = FORMAL_ROOT / "manifests" / "formal_target_gate_20261018.json"
FORMAL_INPUT_MANIFEST = FORMAL_ROOT / "datasets" / "fixed_input_formal_manifest_20261018.json"
FORMAL_GROUND_TRUTH_PATH = FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018.jsonl"
FORMAL_GROUND_TRUTH_MANIFEST_PATH = (
    FORMAL_ROOT / "ground_truth" / "formal_ground_truth_20261018_manifest.json"
)


def formal_batch_root(batch_id: str) -> Path:
    """Return the project-scoped E2 output root independent of the caller's cwd."""
    return FORMAL_ROOT / "runs" / batch_id


def load_formal_fixed_input_pack(
    path: Path,
    *,
    manifest_path: Path = FORMAL_INPUT_MANIFEST,
) -> FixedInputPack:
    """只加载冻结正式 manifest 明确引用且 hash 匹配的 E2 输入包。"""
    source = Path(path).resolve()
    pack = FixedInputPack.load(source)
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read formal input manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "FROZEN_FORMAL_MINIMUM_TARGET":
        raise ValueError("formal input manifest is not frozen")
    packs = manifest.get("packs")
    if not isinstance(packs, list):
        raise ValueError("formal input manifest has no pack list")
    for entry in packs:
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        referenced = (Path(manifest_path).parent / str(entry["file"])).resolve()
        if referenced != source:
            continue
        if entry.get("pack_id") != pack.pack_id or entry.get("region") != pack.region:
            raise ValueError("formal input manifest identity mismatch")
        if entry.get("source_hash") != pack.source_hash:
            raise ValueError("formal input manifest source_hash mismatch")
        return pack
    raise ValueError(f"pack is not referenced by formal input manifest: {source}")


def build_fixed_input_specs(
    *,
    pack: FixedInputPack,
    model: str,
    batch_id: str,
) -> list[ExperimentRunSpec]:
    return [
        ExperimentRunSpec(
            run_id=f"{batch_id}_{pack.pack_id}_{group}",
            experiment_id="E2",
            group=group,
            county=pack.region,
            task_id=pack.mode,
            mode=pack.mode,
            model=model,
            search_provider="disabled-by-fixed-input-protocol",
            config={
                "batch_id": batch_id,
                "formal_target": True,
                "model": model,
                "group": group,
                "region": pack.region,
                "focus": pack.focus,
                "mode": pack.mode,
                "input_pack_id": pack.pack_id,
                "input_hash": pack.source_hash,
                "search_enabled": False,
                "max_llm_tokens": 2048,
            },
        )
        for group in ("A", "B", "C")
    ]


def _worker_command(spec: ExperimentRunSpec, *, root: Path, pack_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.run_independent_fixed_input_worker",
        "--root",
        str(root.resolve()),
        "--resource-db",
        str((root / "resources.sqlite").resolve()),
        "--input-pack",
        str(pack_path.resolve()),
        "--run-id",
        spec.run_id,
        "--group",
        spec.group,
        "--model",
        spec.model,
        "--batch-id",
        str(spec.config["batch_id"]),
    ]


def run_batch(
    *,
    input_pack: Path,
    batch_id: str | None = None,
    resume: bool = False,
) -> dict[str, str]:
    require_formal_api_gate(FORMAL_GATE_PATH)
    require_frozen_ground_truth(
        FORMAL_GROUND_TRUTH_PATH,
        FORMAL_GROUND_TRUTH_MANIFEST_PATH,
    )
    pack = load_formal_fixed_input_pack(input_pack)
    settings = load_settings()
    batch_id = batch_id or datetime.now(timezone.utc).strftime("e2_%Y%m%dT%H%M%SZ")
    root = formal_batch_root(batch_id)
    if root.exists() and not resume:
        raise FileExistsError(f"formal E2 batch directory already exists: {root}")
    checkpoint_config = {
        "batch_id": batch_id,
        "experiment_id": "E2",
        "model": settings.llm.model,
        "input_pack_id": pack.pack_id,
        "input_hash": pack.source_hash,
        "region": pack.region,
        "mode": pack.mode,
    }
    checkpoint = CheckpointStore(root / "checkpoint.json")
    checkpoint_state = checkpoint.start(config=checkpoint_config, resume=resume)
    ResourceManager(
        root / "resources.sqlite",
        limits={
            (settings.llm.provider, settings.llm.model, "llm"): ResourceLimit(
                24000,
                billing_class=(
                    "paid_authorized"
                    if settings.llm.provider == "deepseek"
                    else "free_confirmed"
                ),
            ),
        },
    )
    specs = build_fixed_input_specs(pack=pack, model=settings.llm.model, batch_id=batch_id)
    results: dict[str, str] = dict(checkpoint_state.get("completed", {}))
    for spec in specs:
        manifest_path = root / spec.run_id / "manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = str(payload.get("status", ""))
            if status in {item.value for item in RunStatus if item not in {
                RunStatus.PLANNED,
                RunStatus.RUNNING,
            }}:
                results[spec.run_id] = status
                checkpoint.record(config=checkpoint_config, run_id=spec.run_id, status=status)
                continue
            raise RuntimeError(
                f"cannot resume non-terminal E2 run: {spec.run_id} ({status or 'missing status'})"
            )
        if spec.run_id in results:
            raise RuntimeError(f"checkpoint references missing E2 run manifest: {spec.run_id}")
        subprocess.run(
            _worker_command(spec, root=root, pack_path=Path(input_pack).resolve()),
            cwd=Path(__file__).resolve().parents[1],
            check=True,
        )
        manifest_path = root / spec.run_id / "manifest.json"
        results[spec.run_id] = json.loads(manifest_path.read_text(encoding="utf-8"))["status"]
        checkpoint.record(
            config=checkpoint_config,
            run_id=spec.run_id,
            status=results[spec.run_id],
        )
    (root / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-pack", type=Path, required=True)
    parser.add_argument("--batch-id")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_batch(
                input_pack=args.input_pack,
                batch_id=args.batch_id,
                resume=args.resume,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
