from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from scripts import run_independent_fixed_input, run_independent_fixed_input_worker
from scripts.run_independent_fixed_input import (
    build_fixed_input_specs,
    formal_batch_root,
    load_formal_fixed_input_pack,
)

from county_research_ai.evaluation.fixed_input import FixedInputPack
from county_research_ai.evaluation.gate import FormalGateError
from county_research_ai.models import RawDoc


def test_e2_specs_freeze_pack_identity_and_disable_search():
    pack = FixedInputPack.create(
        pack_id="pack-1",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=[
            RawDoc(
                title="官方资料",
                url="https://example.gov.cn/source",
                content="资料正文",
                source="gov",
            )
        ],
    )

    specs = build_fixed_input_specs(
        pack=pack,
        model="gemini-3.1-flash-lite",
        batch_id="e2_test",
    )

    assert [spec.group for spec in specs] == ["A", "B", "C"]
    assert all(spec.experiment_id == "E2" for spec in specs)
    assert all(spec.search_provider == "disabled-by-fixed-input-protocol" for spec in specs)
    assert {spec.config["input_hash"] for spec in specs} == {pack.source_hash}
    assert all(spec.config["search_enabled"] is False for spec in specs)
    assert all(spec.config["formal_target"] is True for spec in specs)


def test_e2_batch_root_is_absolute_and_project_scoped():
    root = formal_batch_root("e2_test")

    assert root.is_absolute()
    assert root.parent.name == "runs"
    assert root.parent.parent.name == "independent_comparison"


def test_e2_worker_rechecks_formal_gate_before_loading_or_running(tmp_path, monkeypatch):
    gate = tmp_path / "gate.json"
    precheck = tmp_path / "precheck.json"
    gate.write_text(
        json.dumps({"status": "NOT_RUN", "resource_precheck": "precheck.json"}),
        encoding="utf-8",
    )
    precheck.write_text(
        json.dumps({"gemini": {"billing_boundary": "UNKNOWN"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_independent_fixed_input_worker, "FORMAL_GATE_PATH", gate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_independent_fixed_input_worker",
            "--root",
            str(tmp_path / "runs"),
            "--resource-db",
            str(tmp_path / "resources.sqlite"),
            "--input-pack",
            str(tmp_path / "missing-pack.json"),
            "--run-id",
            "run-1",
            "--group",
            "A",
            "--model",
            "model",
            "--batch-id",
            "batch",
        ],
    )

    with pytest.raises(FormalGateError, match="gate is not open"):
        run_independent_fixed_input_worker.main()


def test_formal_e2_loader_rejects_pack_outside_frozen_manifest(tmp_path):
    pack = FixedInputPack.create(
        pack_id="unlisted-pack",
        region="新地区县",
        focus="特色产业",
        mode="snapshot",
        documents=[
            RawDoc(
                title="官方资料",
                url="https://example.gov.cn/source",
                content="资料正文",
                source="gov",
            )
        ],
    )
    pack_path = tmp_path / "unlisted.json"
    pack.write(pack_path)
    manifest_path = tmp_path / "formal_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "FROZEN_FORMAL_MINIMUM_TARGET",
                "packs": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not referenced by formal input manifest"):
        load_formal_fixed_input_pack(pack_path, manifest_path=manifest_path)


def test_e2_batch_resume_skips_completed_runs(tmp_path, monkeypatch):
    class Settings:
        class LLM:
            provider = "gemini"
            model = "model"

        llm = LLM()

    pack = FixedInputPack.create(
        pack_id="resume-pack",
        region="测试县",
        focus="产业",
        mode="snapshot",
        documents=[
            RawDoc(
                title="官方资料",
                url="https://example.gov.cn/source",
                content="资料正文",
                source="gov",
            )
        ],
    )
    input_pack = tmp_path / "input.json"
    pack.write(input_pack)
    monkeypatch.setattr(run_independent_fixed_input, "FORMAL_ROOT", tmp_path / "formal")
    monkeypatch.setattr(run_independent_fixed_input, "require_formal_api_gate", lambda _: None)
    monkeypatch.setattr(
        run_independent_fixed_input,
        "require_frozen_ground_truth",
        lambda *_: None,
    )
    monkeypatch.setattr(run_independent_fixed_input, "load_settings", lambda: Settings())
    monkeypatch.setattr(
        run_independent_fixed_input,
        "load_formal_fixed_input_pack",
        lambda path: pack,
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        root = Path(command[command.index("--root") + 1])
        run_id = command[command.index("--run-id") + 1]
        run_dir = root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps({"run_id": run_id, "status": "VALID"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(run_independent_fixed_input.subprocess, "run", fake_run)

    first = run_independent_fixed_input.run_batch(
        input_pack=input_pack,
        batch_id="resume-e2",
    )
    call_count = len(calls)
    second = run_independent_fixed_input.run_batch(
        input_pack=input_pack,
        batch_id="resume-e2",
        resume=True,
    )

    assert first == second
    assert len(calls) == call_count
