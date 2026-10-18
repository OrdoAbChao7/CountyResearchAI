from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr
from scripts.run_independent_smoke import (
    _artifact_pair,
    _build_experiment_search,
    _focus_for_spec,
    _instrumented_usage_known,
    _pilot_worker_command,
    _require_nonempty_report,
    _smoke_settings,
    build_c_probe_spec,
    build_pilot_specs,
    build_smoke_specs,
)

from county_research_ai.evaluation.experiment_models import RunArtifact
from county_research_ai.evaluation.resource_manager import (
    ResourceLimit,
    ResourceManager,
)
from county_research_ai.search.web_search import DeepSeekSearchProvider


def test_smoke_specs_cover_two_development_regions_and_three_groups():
    specs = build_smoke_specs(model="gemini-3.1-flash-lite", search_provider="tavily", batch_id="batch")

    assert len(specs) == 6
    assert {spec.group for spec in specs} == {"A", "B", "C"}
    assert {spec.county for spec in specs} == {"安吉县", "信丰县"}
    assert all(spec.experiment_id == "E1" for spec in specs)


def test_smoke_settings_support_a_low_budget_probe():
    settings = _smoke_settings(max_tokens=512, max_results=1, tasks=["industry_status"])

    assert settings.llm.max_tokens == 512
    assert settings.llm.tasks == ["industry_status"]
    assert settings.search.max_results == 1


def test_c_probe_spec_is_single_strict_real_run():
    spec = build_c_probe_spec(model="gemini-3.1-flash-lite", search_provider="tavily", batch_id="probe")

    assert spec.group == "C"
    assert spec.county == "安吉县"
    assert spec.config["max_llm_tokens"] == 512


def test_pilot_specs_use_new_region_and_all_three_groups():
    specs = build_pilot_specs(model="model", search_provider="tavily", batch_id="pilot")

    assert [spec.group for spec in specs] == ["A", "B", "C"]
    assert {spec.county for spec in specs} == {"于都县"}
    assert all(spec.config["pilot"] is True for spec in specs)


def test_artifact_pair_normalizes_relative_run_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    artifact = RunArtifact(Path("run"))
    artifact.write_text("report.md", "report")

    path, digest = _artifact_pair(artifact, "report.md")

    assert path.is_absolute()
    assert len(digest) == 64


def test_pilot_worker_command_is_process_isolated(tmp_path):
    spec = build_pilot_specs(model="model", search_provider="tavily", batch_id="pilot")[0]

    command = _pilot_worker_command(spec, tmp_path)

    assert command[0].endswith("python.exe")
    assert command[1:3] == ["-m", "scripts.run_independent_worker"]
    assert "--run-id" in command
    assert spec.run_id in command


def test_pilot_focus_comes_from_frozen_spec():
    spec = build_pilot_specs(model="model", search_provider="tavily", batch_id="pilot")[0]

    assert _focus_for_spec(spec) == "电子信息与纺织服装"


def test_county_research_usage_status_comes_from_instrumented_provider():
    assert _instrumented_usage_known(SimpleNamespace(instrumented_llm=SimpleNamespace(usage_known=True)))
    assert not _instrumented_usage_known(
        SimpleNamespace(instrumented_llm=SimpleNamespace(usage_known=False))
    )
    assert not _instrumented_usage_known(SimpleNamespace(instrumented_llm=None))


def test_empty_research_report_is_rejected_at_experiment_boundary():
    try:
        _require_nonempty_report("  \n")
    except ValueError as exc:
        assert str(exc) == "researcher returned an empty report"
    else:
        raise AssertionError("empty report must not be accepted as a valid experiment artifact")


def test_baseline_search_uses_the_frozen_spec_provider(tmp_path, tmp_settings):
    tmp_settings.search.provider = "deepseek"
    tmp_settings.search.api_key = SecretStr("deepseek-test-key")
    spec = build_pilot_specs(model="deepseek-chat", search_provider="deepseek", batch_id="pilot")[0]
    manager = ResourceManager(
        tmp_path / "resources.sqlite",
        limits={("deepseek", "search", "search"): ResourceLimit(2)},
    )

    managed = _build_experiment_search(tmp_settings, spec, manager)

    assert managed.name == "deepseek"
    assert isinstance(managed._delegate, DeepSeekSearchProvider)
