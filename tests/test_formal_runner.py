from __future__ import annotations

import json
from pathlib import Path

from scripts import run_independent_formal
from scripts.run_independent_formal import (
    build_formal_specs,
    formal_worker_command,
    load_formal_regions,
)


def test_formal_regions_load_as_six_frozen_non_development_regions():
    regions = load_formal_regions()

    assert len(regions) == 6
    assert {region["name"] for region in regions} == {
        "德清县",
        "长汀县",
        "于都县",
        "攀枝花市",
        "白山市",
        "临泽县",
    }
    assert {region["primary_task"] for region in regions} == {
        "snapshot",
        "rise-fall",
        "long-history",
    }


def test_formal_specs_are_balanced_across_three_isolated_groups():
    specs = build_formal_specs(
        model="gemini-3.1-flash-lite",
        search_provider="tavily",
        batch_id="formal_preflight",
        region_names=["德清县", "于都县"],
        repeats=1,
        max_tokens=512,
        max_search_results=1,
    )

    assert len(specs) == 6
    assert {spec.group for spec in specs} == {"A", "B", "C"}
    assert {spec.county for spec in specs} == {"德清县", "于都县"}
    assert all(spec.experiment_id == "E1" for spec in specs)
    assert all(spec.config["formal_target"] is True for spec in specs)
    assert all(spec.config["max_llm_tokens"] == 512 for spec in specs)


def test_formal_worker_command_uses_independent_process(tmp_path):
    spec = build_formal_specs(
        model="model",
        search_provider="tavily",
        batch_id="formal_preflight",
        region_names=["德清县"],
        repeats=1,
        max_tokens=512,
        max_search_results=1,
    )[0]

    command = formal_worker_command(
        spec,
        root=tmp_path,
        resource_db=tmp_path / "resources.sqlite",
    )

    assert command[1:3] == ["-m", "scripts.run_independent_formal_worker"]
    assert "--run-id" in command
    assert spec.run_id in command


def test_formal_batch_resume_skips_completed_runs(tmp_path, monkeypatch):
    class Settings:
        class LLM:
            provider = "gemini"
            model = "model"

        class Search:
            provider = "tavily"

        llm = LLM()
        search = Search()

    monkeypatch.setattr(run_independent_formal, "FORMAL_ROOT", tmp_path / "formal")
    monkeypatch.setattr(run_independent_formal, "require_formal_api_gate", lambda _: None)
    monkeypatch.setattr(run_independent_formal, "require_frozen_ground_truth", lambda *_: None)
    monkeypatch.setattr(run_independent_formal, "load_settings", lambda: Settings())
    monkeypatch.setattr(
        run_independent_formal,
        "load_formal_regions",
        lambda: [{"id": "test", "name": "测试县", "primary_task": "snapshot", "focus": "产业"}],
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

    monkeypatch.setattr(run_independent_formal.subprocess, "run", fake_run)

    first = run_independent_formal.run_batch(
        region_names=["测试县"],
        batch_id="resume-batch",
    )
    call_count = len(calls)
    second = run_independent_formal.run_batch(
        region_names=["测试县"],
        batch_id="resume-batch",
        resume=True,
    )

    assert first == second
    assert len(calls) == call_count
