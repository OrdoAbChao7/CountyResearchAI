from __future__ import annotations

import json

import pytest

from county_research_ai.evaluation.checkpoints import CheckpointStore
from county_research_ai.evaluation.experiment_models import (
    RunArtifact,
    RunManifest,
    RunStatus,
    architecture_version_for_group,
    config_hash,
)


def test_manifest_enforces_valid_lifecycle_and_persists_json(tmp_path):
    manifest = RunManifest.create(
        run_id="run-1",
        experiment_id="exp-1",
        group="A",
        county="新地区县",
        task_id="snapshot-1",
        mode="snapshot",
        model="gemini-3.1-flash-lite",
        search_provider="tavily",
        config={"temperature": 0.1, "max_searches": 2, "architecture_version": "evidence_first_v2"},
    )

    manifest.transition(RunStatus.RUNNING)
    manifest.transition(RunStatus.VALID)
    path = tmp_path / "manifest.json"
    manifest.write(path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "VALID"
    assert loaded["formal_target"] is False
    assert loaded["architecture_version"] == "evidence_first_v2"
    assert loaded["config_hash"] == config_hash(
        {"temperature": 0.1, "max_searches": 2, "architecture_version": "evidence_first_v2"}
    )

    with pytest.raises(ValueError):
        manifest.transition(RunStatus.RUNNING)


def test_manifest_persists_formal_target_scope(tmp_path):
    manifest = RunManifest.create(
        run_id="formal-run",
        experiment_id="E1",
        group="A",
        county="正式县",
        task_id="snapshot",
        mode="snapshot",
        model="gemini-3.1-flash-lite",
        search_provider="tavily",
        config={"formal_target": True, "architecture_version": "deep_legacy"},
    )

    path = tmp_path / "manifest.json"
    manifest.write(path)

    assert json.loads(path.read_text(encoding="utf-8"))["formal_target"] is True
    assert json.loads(path.read_text(encoding="utf-8"))["architecture_version"] == "deep_legacy"


def test_experiment_groups_declare_the_actual_researcher_architecture():
    assert architecture_version_for_group("A") == "traditional_search_baseline"
    assert architecture_version_for_group("B") == "general_ai_baseline"
    assert architecture_version_for_group("C") == "evidence_first_v2"


def test_artifact_writes_json_and_returns_sha256(tmp_path):
    artifact = RunArtifact(tmp_path)

    path, digest = artifact.write_json("response.json", {"answer": "ok"})

    assert path.read_text(encoding="utf-8") == '{"answer":"ok"}'
    assert len(digest) == 64
    assert artifact.sha256(path) == digest


def test_checkpoint_rejects_configuration_drift(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.json")
    store.save(config={"model": "gemini-3.1-flash-lite"}, state={"step": 2})

    assert store.load(config={"model": "gemini-3.1-flash-lite"})["state"] == {"step": 2}
    with pytest.raises(ValueError, match="configuration hash mismatch"):
        store.load(config={"model": "different-model"})


def test_checkpoint_supports_start_record_and_resume(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoint.json")
    config = {"model": "gemini-3.1-flash-lite", "batch": "batch-1"}

    assert store.start(config=config) == {"completed": {}}
    store.record(config=config, run_id="run-1", status="VALID")

    assert store.start(config=config, resume=True) == {
        "completed": {"run-1": "VALID"}
    }
    with pytest.raises(FileExistsError, match="checkpoint already exists"):
        store.start(config=config)
