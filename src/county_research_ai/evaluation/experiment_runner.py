"""隔离实验运行器。"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .experiment_models import RunArtifact, RunManifest, RunStatus
from .resource_manager import ResourceExhaustedError, ResourceManager, ResourceOverrunError


@dataclass(frozen=True)
class ExperimentRunSpec:
    run_id: str
    experiment_id: str
    group: str
    county: str
    task_id: str
    mode: str
    model: str
    search_provider: str
    config: dict[str, Any]


@dataclass(frozen=True)
class ExecutionOutcome:
    artifacts: dict[str, tuple[Path, str]]
    usage_known: bool
    mock_detected: bool = False
    resource_accounting_valid: bool = True


Executor = Callable[[RunArtifact], ExecutionOutcome]


class ExperimentRunner:
    def __init__(self, root: Path, resource_manager: ResourceManager) -> None:
        self.root = Path(root).resolve()
        self.resource_manager = resource_manager

    def run(self, spec: ExperimentRunSpec, execute: Executor) -> RunManifest:
        started = time.perf_counter()
        run_dir = self.root / spec.run_id
        if run_dir.exists():
            raise FileExistsError(f"run directory already exists: {run_dir}")
        run_dir.mkdir(parents=True)

        manifest = RunManifest.create(
            run_id=spec.run_id,
            experiment_id=spec.experiment_id,
            group=spec.group,
            county=spec.county,
            task_id=spec.task_id,
            mode=spec.mode,
            model=spec.model,
            search_provider=spec.search_provider,
            config=spec.config,
        )
        manifest_path = run_dir / "manifest.json"
        manifest.write(manifest_path)
        manifest.transition(RunStatus.RUNNING)
        manifest.write(manifest_path)

        try:
            outcome = execute(RunArtifact(run_dir))
            resource_usage, active_leases = _run_resource_usage(
                self.resource_manager.snapshot(), spec.run_id
            )
            manifest.resource_usage = resource_usage
            manifest.artifacts = {
                name: f"{path.relative_to(run_dir)}:{digest}"
                for name, (path, digest) in outcome.artifacts.items()
            }
            if outcome.mock_detected:
                manifest.transition(RunStatus.INVALID_MOCK, error="Mock component or output detected")
            elif active_leases or not outcome.resource_accounting_valid:
                manifest.transition(
                    RunStatus.INVALID_RESOURCE_ACCOUNTING,
                    error="resource lease was not fully accounted",
                )
            elif not outcome.usage_known:
                manifest.transition(
                    RunStatus.INVALID_USAGE_UNKNOWN,
                    error="provider usage was unavailable",
                )
            else:
                manifest.transition(RunStatus.VALID)
        except Exception as exc:  # noqa: BLE001
            _, active_leases = _run_resource_usage(
                self.resource_manager.snapshot(), spec.run_id
            )
            if active_leases:
                status = RunStatus.INVALID_RESOURCE_ACCOUNTING
                error = f"{type(exc).__name__}: {exc}; unsettled resource lease remains"
            elif _has_resource_overrun(exc):
                status = RunStatus.INVALID_RESOURCE_ACCOUNTING
                error = f"{type(exc).__name__}: {exc}"
            elif _has_resource_exhaustion(exc):
                status = RunStatus.BLOCKED
                error = f"{type(exc).__name__}: {exc}"
            else:
                status = RunStatus.FAILED
                error = f"{type(exc).__name__}: {exc}"
            manifest.transition(status, error=error)
        finally:
            manifest.duration_seconds = round(time.perf_counter() - started, 6)
            resource_usage, _ = _run_resource_usage(
                self.resource_manager.snapshot(), spec.run_id
            )
            manifest.resource_usage = resource_usage
            manifest.write(manifest_path)
        return manifest


def _has_resource_exhaustion(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ResourceExhaustedError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _has_resource_overrun(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ResourceOverrunError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_resource_usage(snapshot, run_id: str) -> tuple[dict[str, int], bool]:
    usage: dict[str, int] = {}
    active = False
    for event in snapshot.events:
        if event["run_id"] != run_id:
            continue
        key = f"{event['provider']}:{event['model']}:{event['kind']}"
        if event["status"] == "reserved":
            active = True
            continue
        usage[key] = usage.get(key, 0) + int(event["units"])
    return dict(sorted(usage.items())), active
