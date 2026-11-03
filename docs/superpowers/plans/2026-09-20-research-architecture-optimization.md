# Research Architecture Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the video-free default branch so Workflow and Agent share one typed research application, mode dispatch is registry-based, and configuration plus infrastructure are composed at one boundary without breaking public behavior.

**Architecture:** Introduce domain/application/mode/bootstrap boundaries incrementally behind the existing `ResearchPipeline`, `models`, and CLI compatibility surfaces. Extract one tested use case at a time, then convert Workflow and Agent to thin orchestrators over the shared application.

**Tech Stack:** Python 3.13, Pydantic v2, Click, pytest, Ruff, mypy, Jinja2, OpenAI-compatible SDK, local filesystem storage.

**Spec:** `docs/superpowers/specs/2026-09-20-research-architecture-optimization-design.md`

**Prerequisite:** Complete `docs/superpowers/plans/2026-09-20-video-branch-separation.md` and remain on the video-free `master` branch.

## Global Constraints

- Preserve Workflow and Agent CLI arguments, including the legacy no-subcommand Workflow invocation.
- Preserve `snapshot`, `rise-fall`, `long-history`, and the `industry` alias.
- Preserve `.env` and `settings.yaml` keys, report names, cache JSON, data paths, and trace paths.
- Preserve documented imports from `county_research_ai.models`, `ResearchPipeline.run()`, and `create_default_pipeline()`.
- Business methods must not call global `get_settings()` after their dependencies have been migrated.
- Use tests before implementation and commit after each independently reviewable task.

## Review Focus

- A caller reuses the same `ResearchRequest` after a run: mode normalization must not mutate it.
- Search returns no documents and focus is omitted: the application must select the existing `特色农业` fallback and still produce a report.
- A stale processed cache exists while `no_cache=True`: processing must ignore the cache.
- An Agent planner requests a different mode or repeats a completed action: user mode remains authoritative and completed work is not repeated.
- A real provider raises 429/503 or a storage error: stage, retryability, and safe context are retained without exposing credentials.

---

### Task 1: Lock Existing Research Behavior and Dependency Rules

**Files:**
- Create: `tests/test_research_contract.py`
- Create: `tests/test_architecture_imports.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: current video-free research implementation.
- Produces: compatibility and import-boundary tests used throughout the refactor.

- [ ] **Step 1: Add a request immutability characterization test**

Add to `tests/test_research_contract.py`:

```python
import pytest

from county_research_ai.config import reset_settings
from county_research_ai.models import ResearchRequest
from county_research_ai.pipeline import create_default_pipeline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_settings()
    yield tmp_path
    reset_settings()


def test_pipeline_does_not_mutate_request_mode(isolated_env):
    request = ResearchRequest(county="安吉县", focus="竹产业", mode="industry")

    create_default_pipeline().run(request)

    assert request.mode == "industry"
```

- [ ] **Step 2: Add compatibility tests for all mode outputs**

Add a parametrized test that invokes Mock mode for `snapshot`, `rise-fall`, and `long-history`, then asserts the report path exists, contains the county, and retains the current focus/default focus naming.

```python
import pytest


@pytest.mark.parametrize(
    ("mode", "focus"),
    [("snapshot", "竹产业"), ("rise-fall", None), ("long-history", None)],
)
def test_all_modes_preserve_report_contract(isolated_env, mode, focus):
    request = ResearchRequest(county="安吉县", focus=focus, mode=mode)
    report, path = create_default_pipeline().run(request)

    assert path.exists()
    assert report.county.name == "安吉县"
    assert "安吉县" in path.read_text(encoding="utf-8")
```

- [ ] **Step 3: Add an import-contract scanner**

Create `tests/test_architecture_imports.py` with a helper that parses Python files using `ast` and returns imported module names. Add assertions that future `domain/` modules do not import `config`, `agent`, `click`, or `infrastructure`, and future `application/` modules do not import concrete modules ending in `web_search`, `local_fs`, or `client`.

```python
import ast
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src/county_research_ai"


def imports_under(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*.py") if root.exists() else []:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
    return names


def test_domain_has_no_outward_dependencies():
    imports = imports_under(SRC / "domain")
    assert not any(name.endswith(("config", "agent")) or name == "click" for name in imports)


def test_application_does_not_import_concrete_adapters():
    imports = imports_under(SRC / "application")
    assert not any(name.endswith(("web_search", "local_fs", "llm.client")) for name in imports)
```

- [ ] **Step 4: Run characterization tests**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest tests/test_research_contract.py tests/test_architecture_imports.py tests/test_pipeline.py -q
```

Expected: the immutability test fails because the current Pipeline changes `industry` to `snapshot`; other characterization tests pass.

- [ ] **Step 5: Commit tests before implementation**

```powershell
git add tests/test_research_contract.py tests/test_architecture_imports.py tests/test_pipeline.py
git commit -m "test: lock research architecture contracts"
```

### Task 2: Introduce Canonical Modes and Typed Run Context

**Files:**
- Create: `src/county_research_ai/domain/__init__.py`
- Create: `src/county_research_ai/domain/modes.py`
- Create: `src/county_research_ai/application/__init__.py`
- Create: `src/county_research_ai/application/context.py`
- Create: `src/county_research_ai/application/results.py`
- Create: `tests/test_application_context.py`
- Modify: `src/county_research_ai/pipeline.py`

**Interfaces:**
- Consumes: existing research models.
- Produces: `normalize_mode()`, `normalize_request()`, `ResearchContext`, and `ResearchRunResult`.

- [ ] **Step 1: Write failing mode and context tests**

Create `tests/test_application_context.py`:

```python
from county_research_ai.application.context import ResearchContext
from county_research_ai.domain.modes import normalize_mode, normalize_request
from county_research_ai.models import ResearchRequest


def test_industry_alias_normalizes_without_mutating_request():
    request = ResearchRequest(county="安吉县", focus="竹产业", mode="industry")

    normalized = normalize_request(request)

    assert normalized.mode == "snapshot"
    assert request.mode == "industry"


def test_unknown_mode_is_rejected():
    try:
        normalize_mode("rise_fall_analysis")
    except ValueError as exc:
        assert "unsupported research mode" in str(exc)
    else:
        raise AssertionError("unknown mode was accepted")


def test_context_derives_county_from_normalized_request():
    context = ResearchContext.from_request(
        ResearchRequest(county="安吉县", mode="snapshot")
    )
    assert context.county.name == "安吉县"
    assert context.focus == ""
```

- [ ] **Step 2: Run the tests to verify missing modules fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_application_context.py -q
```

Expected: import failure for `county_research_ai.application.context`.

- [ ] **Step 3: Implement canonical mode normalization**

Create `domain/modes.py`:

```python
from typing import Literal, cast

from ..models import ResearchRequest

ResearchMode = Literal["snapshot", "rise-fall", "long-history"]
_ALIASES = {"snapshot": "snapshot", "industry": "snapshot", "rise-fall": "rise-fall", "long-history": "long-history"}


def normalize_mode(value: str) -> ResearchMode:
    normalized = _ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"unsupported research mode: {value}")
    return cast(ResearchMode, normalized)


def normalize_request(request: ResearchRequest) -> ResearchRequest:
    return request.model_copy(deep=True, update={"mode": normalize_mode(request.mode)})
```

- [ ] **Step 4: Implement context and result models**

Create `application/context.py` with `ResearchContext(BaseModel)`, fields for normalized request, CountyInfo, focus, raw docs, discovery, processed evidence, the three mode-specific analysis fields, report, report path, and `from_request()` that calls `normalize_request()`.

Create `application/results.py`:

```python
from pathlib import Path
from pydantic import BaseModel
from ..models import ResearchReport


class ResearchRunResult(BaseModel):
    report: ResearchReport
    report_path: Path
```

- [ ] **Step 5: Make the compatibility Pipeline normalize by copy**

At the start of `ResearchPipeline.run()`, replace in-place mode mutation with:

```python
from .domain.modes import normalize_request

request = normalize_request(request)
```

- [ ] **Step 6: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_application_context.py tests/test_research_contract.py tests/test_pipeline.py -q
git add src/county_research_ai/domain src/county_research_ai/application tests/test_application_context.py src/county_research_ai/pipeline.py
git commit -m "feat: add typed research run context"
```

Expected: all selected tests pass, including request immutability.

### Task 3: Define Application Ports and Add Mode Handlers

**Files:**
- Create: `src/county_research_ai/ports/__init__.py`
- Create: `src/county_research_ai/ports/search.py`
- Create: `src/county_research_ai/ports/processing.py`
- Create: `src/county_research_ai/ports/discovery.py`
- Create: `src/county_research_ai/ports/storage.py`
- Create: `src/county_research_ai/ports/analysis.py`
- Create: `src/county_research_ai/ports/reporting.py`
- Create: `src/county_research_ai/modes/__init__.py`
- Create: `src/county_research_ai/modes/base.py`
- Create: `src/county_research_ai/modes/snapshot.py`
- Create: `src/county_research_ai/modes/rise_fall.py`
- Create: `src/county_research_ai/modes/long_history.py`
- Create: `src/county_research_ai/modes/registry.py`
- Create: `tests/test_mode_registry.py`

**Interfaces:**
- Consumes: `ResearchContext` from Task 2 and existing analyzers/renderers.
- Produces: structural application ports, `RenderedReport`, `ResearchModeHandler`, and `ModeRegistry.get(mode)`.

- [ ] **Step 1: Write failing registry tests**

```python
from county_research_ai.modes.registry import ModeRegistry


class StubHandler:
    name = "snapshot"
    default_focus = "特色农业"


def test_registry_returns_registered_handler():
    handler = StubHandler()
    assert ModeRegistry([handler]).get("snapshot") is handler


def test_registry_rejects_duplicate_mode():
    try:
        ModeRegistry([StubHandler(), StubHandler()])
    except ValueError as exc:
        assert "duplicate research mode" in str(exc)
    else:
        raise AssertionError("duplicate mode was accepted")


def test_registry_rejects_unknown_mode():
    try:
        ModeRegistry([StubHandler()]).get("long-history")
    except ValueError as exc:
        assert "unsupported research mode" in str(exc)
    else:
        raise AssertionError("unknown mode was accepted")
```

- [ ] **Step 2: Run registry tests and verify missing module failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mode_registry.py -q
```

- [ ] **Step 3: Implement structural application ports**

Define dependency protocols without importing concrete infrastructure. The required signatures are:

```python
# ports/search.py
class SearchPort(Protocol):
    def collect(
        self, county: str, focus: str, max_results: int, *, mode: ResearchMode
    ) -> list[RawDoc]: ...


# ports/processing.py
class ProcessingPort(Protocol):
    def process(
        self, raw_docs: list[RawDoc], *, county: CountyInfo, focus: str
    ) -> ProcessedData: ...


# ports/discovery.py
class DiscoveryPort(Protocol):
    def discover_focus(
        self, *, county: CountyInfo, raw_docs: list[RawDoc]
    ) -> DiscoveryResult: ...


# ports/storage.py
class StoragePort(Protocol):
    def save_raw(self, county: str, docs: list[RawDoc]) -> Path: ...
    def load_processed(
        self, county: str, focus: str, max_age_hours: int = 0
    ) -> ProcessedData | None: ...
    def save_processed(
        self, county: str, focus: str, data: ProcessedData
    ) -> Path: ...
    def save_report(self, filename: str, content: str) -> Path: ...
```

In `ports/analysis.py`, define protocols matching `LLMAnalyzer`, `RiseFallAnalyzer`, and `LongHistoryAnalyzer`. In `ports/reporting.py`, define protocols matching `ReportRenderer`, `RiseFallReportRenderer`, and `LongHistoryReportRenderer`, plus:

```python
FilenameRenderer = Callable[[str, dict[str, str]], str]
```

Keep these modules limited to `typing`, `pathlib`, domain/model types, and `ResearchMode`; they must not import `config`, `llm`, `search`, `storage`, or concrete renderers.

- [ ] **Step 4: Implement handler contracts and registry**

Create `modes/base.py`:

```python
from typing import Protocol
from pydantic import BaseModel
from ..application.context import ResearchContext
from ..models import ResearchReport


class RenderedReport(BaseModel):
    report: ResearchReport
    markdown: str


class ResearchModeHandler(Protocol):
    name: str
    default_focus: str
    def analyze(self, context: ResearchContext) -> ResearchContext: ...
    def render(self, context: ResearchContext) -> RenderedReport: ...
```

Implement `ModeRegistry` as a constructor-injected mapping that rejects duplicates and unknown names.

- [ ] **Step 5: Implement the three adapters around existing analyzers/renderers**

Each handler receives only its matching analyzer/reporting protocols in `__init__`, updates only its matching analysis field using `context.model_copy(update=...)`, and returns a compatibility `ResearchReport` plus Markdown. Use these fixed identities and fallbacks:

```python
class SnapshotModeHandler:
    name = "snapshot"
    default_focus = "特色农业"

class RiseFallModeHandler:
    name = "rise-fall"
    default_focus = "兴衰规律"

class LongHistoryModeHandler:
    name = "long-history"
    default_focus = "长周期兴衰史"
```

`analyze()` must require `context.processed`, call the injected analyzer with the existing argument shape, and populate exactly one of `snapshot_analyses`, `rise_fall_analysis`, or `long_history_analysis`. `render()` must preserve the current Snapshot title map and the exact Rise-Fall/Long-History section-title lists, returning `RenderedReport(report=..., markdown=...)`. Move those title constructions from Pipeline/Agent Tools into the handlers so there is exactly one implementation per mode.

- [ ] **Step 6: Add dispatch and port-boundary tests**

Test each handler writes only its matching context field and that Registry dispatch returns the correct handler for all three canonical modes. Extend `tests/test_architecture_imports.py` so `ports/` rejects imports ending in `config`, `llm.client`, `web_search`, `local_fs`, and all concrete renderer modules.

- [ ] **Step 7: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mode_registry.py tests/test_architecture_imports.py tests/test_reporting.py tests/test_long_history_renderer.py -q
.\.venv\Scripts\python.exe -m mypy src/county_research_ai/ports src/county_research_ai/modes
git add src/county_research_ai/ports src/county_research_ai/modes tests/test_mode_registry.py tests/test_architecture_imports.py
git commit -m "feat: register research mode handlers"
```

### Task 4: Extract the Shared Research Application

**Files:**
- Create: `src/county_research_ai/application/config.py`
- Create: `src/county_research_ai/application/research.py`
- Create: `tests/test_research_application.py`
- Modify: `src/county_research_ai/exceptions.py`

**Interfaces:**
- Consumes: ResearchContext and ModeRegistry.
- Produces: `ResearchApplication.collect_materials()`, `discover_focus()`, `build_evidence()`, `analyze()`, and `render_report()`.

- [ ] **Step 1: Write failing application-stage tests**

Use injected static collector, storage, processor, discovery analyzer, and ModeRegistry. Assert:

```python
context = application.collect_materials(context)
assert context.raw_docs

context = application.discover_focus(context)
assert context.focus == "竹产业"

context = application.build_evidence(context)
assert context.processed is not None

context = application.analyze(context)
assert context.snapshot_analyses

result = application.render_report(context)
assert result.report_path.exists()
```

Add explicit tests that missing focus plus empty search falls back to `特色农业`, and `no_cache=True` never calls `storage.load_processed()`. Add failure tests where an injected dependency raises an error carrying `status_code=429` or `503`; assert the resulting `ResearchStageError` has the correct stage, `retryable=True`, an unchanged `__cause__`, and no API key/header value in its context or string form.

- [ ] **Step 2: Run tests to verify missing application failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_research_application.py -q
```

- [ ] **Step 3: Add injected application policy**

Create immutable `ResearchApplicationConfig` with:

```python
@dataclass(frozen=True)
class ResearchApplicationConfig:
    max_search_results: int
    cache_enabled: bool
    cache_ttl_hours: int
    report_filename_template: str
```

- [ ] **Step 4: Implement the five use cases**

Implement this constructor boundary:

```python
class ResearchApplication:
    def __init__(
        self,
        *,
        search: SearchPort,
        storage: StoragePort,
        processor: ProcessingPort,
        discovery: DiscoveryPort,
        modes: ModeRegistry,
        config: ResearchApplicationConfig,
        render_filename: FilenameRenderer,
        clock: Callable[[], datetime] = utc_now,
    ) -> None: ...

    def collect_materials(self, context: ResearchContext) -> ResearchContext: ...
    def discover_focus(self, context: ResearchContext) -> ResearchContext: ...
    def build_evidence(self, context: ResearchContext) -> ResearchContext: ...
    def analyze(self, context: ResearchContext) -> ResearchContext: ...
    def render_report(self, context: ResearchContext) -> ResearchRunResult: ...
```

Copy the current stage behavior without importing `get_settings()` or concrete provider classes. `collect_materials()` passes the canonical mode to `SearchPort.collect()`. `discover_focus()` uses the selected Handler's `default_focus` whenever discovery has no selected result, including empty search results. `build_evidence()` computes cache hours as zero when `request.options["no_cache"]` is true; otherwise it uses the injected cache policy, then persists processed/raw data after a miss. `analyze()` and `render_report()` fetch the Handler from `ModeRegistry`. `render_report()` calls the injected filename renderer with the existing template and UTC date, saves Markdown through `StoragePort`, and returns `ResearchRunResult`.

- [ ] **Step 5: Add structured stage errors**

In `exceptions.py`, add this compatible shape:

```python
class ResearchStageError(CountyResearchAIError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, context=context)
        self.code = code
        self.stage = stage
        self.retryable = retryable
```

Wrap collector, analyzer, renderer, and storage failures at application boundaries using `raise ResearchStageError(...) from exc`. Retryability is true for timeouts/connections and status codes `408`, `429`, `500`, `502`, `503`, or `504`. Build context from an allowlist (`county`, `focus`, `mode`, `status_code`) rather than copying arbitrary exception context, headers, prompts, or credentials.

- [ ] **Step 6: Run application and import-contract tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_research_application.py tests/test_architecture_imports.py -q
.\.venv\Scripts\python.exe -m mypy src/county_research_ai/application src/county_research_ai/modes
```

- [ ] **Step 7: Commit**

```powershell
git add src/county_research_ai/application src/county_research_ai/exceptions.py tests/test_research_application.py
git commit -m "feat: extract shared research application"
```

### Task 5: Move Workflow onto the Shared Application

**Files:**
- Create: `src/county_research_ai/application/workflow.py`
- Create: `tests/test_workflow_runner.py`
- Modify: `src/county_research_ai/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: ResearchApplication from Task 4.
- Produces: `WorkflowRunner.run(request) -> ResearchRunResult`; compatibility `ResearchPipeline.run()` delegates to it.

- [ ] **Step 1: Write failing Workflow order and policy tests**

Use a recording fake application and assert exact calls:

```python
assert calls == ["collect", "discover", "evidence", "analyze", "report"]
```

For a request with focus, assert `discover` is omitted. Add a fail-fast test where `collect` raises `ResearchStageError` and later stages are not called.

- [ ] **Step 2: Run tests to verify WorkflowRunner is missing**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_runner.py -q
```

- [ ] **Step 3: Implement WorkflowRunner**

Constructor inputs:

```python
class WorkflowRunner:
    def __init__(self, application: ResearchApplication, *, stages: PipelineStages, fail_fast: bool): ...
    def run(self, request: ResearchRequest) -> ResearchRunResult: ...
```

It initializes ResearchContext, calls enabled stages in order, and applies the existing fail-fast policy without containing search, cache, analysis, mode, or rendering logic.

- [ ] **Step 4: Convert ResearchPipeline to a compatibility facade**

Keep its public constructor attributes used by tests. Add an injected `workflow_runner` and implement:

```python
def run(self, request: ResearchRequest) -> tuple[ResearchReport, Path]:
    result = self.workflow_runner.run(request)
    return result.report, result.report_path
```

Delete old duplicated `_run_rise_fall`, `_run_long_history`, and stage implementations only after compatibility tests pass.

- [ ] **Step 5: Run Workflow and Pipeline tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_runner.py tests/test_pipeline.py tests/test_research_contract.py -q
```

Expected: all tests pass for three modes and legacy imports.

- [ ] **Step 6: Commit**

```powershell
git add src/county_research_ai/application/workflow.py src/county_research_ai/pipeline.py tests/test_workflow_runner.py tests/test_pipeline.py
git commit -m "refactor: run workflow through shared application"
```

### Task 6: Convert Agent Tools to Thin Application Adapters

**Files:**
- Modify: `src/county_research_ai/agent/base.py`
- Modify: `src/county_research_ai/agent/models.py`
- Modify: `src/county_research_ai/agent/tools.py`
- Modify: `src/county_research_ai/agent/factory.py`
- Modify: `src/county_research_ai/agent/runtime.py`
- Modify: `tests/test_agent_tools.py`
- Create: `tests/test_agent_application_parity.py`

**Interfaces:**
- Consumes: ResearchApplication and ResearchContext.
- Produces: Agent tools that only convert state/context and invoke one application use case.

- [ ] **Step 1: Write a failing delegation test**

Inject a recording application into the tool context and assert each tool calls exactly one method. For example:

```python
result = ResearchAnalysisTool(context).execute(state, {})
assert application.calls == ["analyze"]
assert result.state_patch["snapshot_analyses"]
```

Assert Agent Tools no longer expose concrete analyzer or renderer fields.

Add an error-delegation case where the fake application raises `ResearchStageError(code="analyze_failed", stage="analyze", retryable=True)`. Assert the returned `ToolResult` preserves `error_code`, `retryable`, and a safe message, and the resulting `AgentError`/trace retain those fields.

- [ ] **Step 2: Write Workflow/Agent parity coverage**

Create `tests/test_agent_application_parity.py` using one fake ResearchApplication. Run a Workflow and the fallback Agent tool sequence for the same request, then assert county, normalized mode, focus, report path, and selected handler match.

- [ ] **Step 3: Run tests and verify current duplicate context fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py tests/test_agent_application_parity.py -q
```

- [ ] **Step 4: Replace ResearchToolContext dependencies**

Change it to:

```python
@dataclass(frozen=True)
class ResearchToolContext:
    application: ResearchApplication
```

Add explicit `state_to_context()` and `context_to_patch()` helpers. Each tool calls one application method and returns a controlled state patch. Keep request mode authoritative; ignore planner-supplied mismatched mode aliases after logging.

Add backward-compatible defaults to the Agent result models:

```python
class ToolResult(BaseModel):
    # existing fields stay unchanged
    error_code: str = ""
    retryable: bool = False


class AgentError(BaseModel):
    # existing fields stay unchanged
    retryable: bool = False
```

The base tool adapter converts `ResearchStageError` to these fields; `AgentRuntime` copies them into `AgentError` and Trace instead of flattening every failure to `tool_error`.

- [ ] **Step 5: Update Agent factory and run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py tests/test_agent_runtime.py tests/test_agent_planner.py tests/test_agent_application_parity.py -q
.\.venv\Scripts\python.exe -m ruff check src/county_research_ai/agent tests/test_agent_*.py
```

- [ ] **Step 6: Commit**

```powershell
git add src/county_research_ai/agent/base.py src/county_research_ai/agent/models.py src/county_research_ai/agent/tools.py src/county_research_ai/agent/factory.py src/county_research_ai/agent/runtime.py tests/test_agent_tools.py tests/test_agent_application_parity.py
git commit -m "refactor: share research application with agent"
```

### Task 7: Centralize Production Composition

**Files:**
- Create: `src/county_research_ai/infrastructure/__init__.py`
- Create: `src/county_research_ai/infrastructure/search_adapter.py`
- Create: `src/county_research_ai/bootstrap/__init__.py`
- Create: `src/county_research_ai/bootstrap/container.py`
- Create: `tests/test_app_container.py`
- Create: `tests/test_search_adapter.py`
- Modify: `src/county_research_ai/pipeline.py`
- Modify: `src/county_research_ai/agent/factory.py`

**Interfaces:**
- Consumes: WorkflowRunner, ResearchApplication, ModeRegistry, existing infrastructure.
- Produces: `AppContainer`, `create_app_container()`, compatibility factories.

- [ ] **Step 1: Write failing container tests**

```python
def test_container_loads_settings_once(monkeypatch):
    calls = []
    monkeypatch.setattr("county_research_ai.bootstrap.container.get_settings", lambda: calls.append(1) or settings)
    container = create_app_container()
    assert len(calls) == 1
    assert container.workflow.application is container.application


def test_agent_and_workflow_share_application(container):
    agent = container.create_agent(save_trace=False)
    assert agent.registry.get("analyze_research").context.application is container.application
```

Add adapter tests proving both a Collector-style dependency and a plain Mock `SearchProvider` satisfy the same `SearchPort.collect()` contract, receive the canonical mode, and deduplicate URLs.

- [ ] **Step 2: Run tests to verify container is missing**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app_container.py -q
```

- [ ] **Step 3: Implement the search infrastructure adapters**

`CollectorSearchAdapter.collect()` delegates directly to the injected collector. `ProviderSearchAdapter.collect()` owns the legacy three-query fallback currently duplicated in Pipeline and Agent Tools, calls the injected provider's `search()`, and deduplicates non-empty URLs. Neither adapter reads Settings; max results and mode arrive as method arguments.

- [ ] **Step 4: Implement AppContainer**

Create a frozen dataclass containing Settings, LLMClient, SearchPort, StoragePort, ResearchApplication, WorkflowRunner, and ModeRegistry. `create_app_container(settings: Settings | None = None)` loads settings once, selects real versus Mock providers using existing rules, wraps the selected search dependency in the matching infrastructure adapter, constructs `DocumentProcessor` with `settings.quality`, and wires all analyzers, renderers, handlers, application config, and runners. No object created by the container may independently load Settings when an explicit Settings argument is available.

- [ ] **Step 5: Delegate compatibility factories**

Implement:

```python
def create_default_pipeline() -> ResearchPipeline:
    return create_app_container().create_pipeline()


def create_default_agent(*, max_steps=8, save_trace=True, trace_root=None) -> AgentRuntime:
    return create_app_container().create_agent(
        max_steps=max_steps, save_trace=save_trace, trace_root=trace_root
    )
```

- [ ] **Step 6: Run factory, adapter, Pipeline, and Agent tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_app_container.py tests/test_search_adapter.py tests/test_pipeline.py tests/test_agent_cli.py tests/test_agent_tools.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add src/county_research_ai/infrastructure src/county_research_ai/bootstrap src/county_research_ai/pipeline.py src/county_research_ai/agent/factory.py tests/test_app_container.py tests/test_search_adapter.py
git commit -m "refactor: centralize application composition"
```

### Task 8: Split Research Models Behind Compatibility Exports

**Files:**
- Create: `src/county_research_ai/domain/common.py`
- Create: `src/county_research_ai/domain/evidence.py`
- Create: `src/county_research_ai/domain/snapshot.py`
- Create: `src/county_research_ai/domain/rise_fall.py`
- Create: `src/county_research_ai/domain/long_history.py`
- Create: `src/county_research_ai/domain/reports.py`
- Modify: `src/county_research_ai/models.py`
- Create: `tests/test_model_compatibility.py`

**Interfaces:**
- Consumes: existing Pydantic research model definitions.
- Produces: focused domain modules and backward-compatible `county_research_ai.models` exports.

- [ ] **Step 1: Write serialization and identity compatibility tests**

```python
from county_research_ai.domain.evidence import RawDoc as DomainRawDoc
from county_research_ai.models import RawDoc


def test_legacy_model_import_reexports_domain_class():
    assert RawDoc is DomainRawDoc


def test_raw_doc_json_remains_compatible():
    payload = {"title": "统计公报", "url": "https://example.com", "content": "正文"}
    assert RawDoc.model_validate(payload).model_dump()["title"] == "统计公报"
```

Add equivalent identity assertions for ResearchRequest, ProcessedData, AnalysisResult, ResearchReport, CountyRiseFallAnalysis, and CountyLongHistoryAnalysis.

- [ ] **Step 2: Run tests and verify domain modules are missing**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_compatibility.py -q
```

- [ ] **Step 3: Move model groups without changing fields**

Use these exact ownership groups:

- `common.py`: `_utcnow`, CountyInfo, ResearchRequest;
- `evidence.py`: RawDoc, ProcessedData;
- `snapshot.py`: AnalysisResult, DiscoveryCandidate, DiscoveryResult;
- `rise_fall.py`: rise-fall lifecycle and analysis models;
- `long_history.py`: historical periods, factors, patterns, and analysis models;
- `reports.py`: ReportSection, ResearchReport.

Resolve cross-module imports explicitly and keep field defaults unchanged.

- [ ] **Step 4: Replace models.py with explicit re-exports**

`models.py` imports and lists every public research model in `__all__`. It contains no model implementation. Update `domain/modes.py` and all new `domain/`, `ports/`, `application/`, and `modes/` modules to import sibling domain modules directly; only legacy compatibility code may continue importing through `county_research_ai.models`.

- [ ] **Step 5: Run model, cache, renderer, and full tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_compatibility.py tests/test_models.py tests/test_storage.py tests/test_reporting.py tests/test_long_history_renderer.py -q
.\.venv\Scripts\python.exe -m mypy src/county_research_ai/domain src/county_research_ai/ports src/county_research_ai/application src/county_research_ai/modes
```

- [ ] **Step 6: Commit**

```powershell
git add src/county_research_ai/domain src/county_research_ai/models.py tests/test_model_compatibility.py
git commit -m "refactor: split research domain models"
```

### Task 9: Make CLI a Thin Interface and Finalize Compatibility Layers

**Files:**
- Create: `src/county_research_ai/interfaces/__init__.py`
- Create: `src/county_research_ai/interfaces/cli.py`
- Modify: `src/county_research_ai/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_agent_cli.py`

**Interfaces:**
- Consumes: AppContainer factories.
- Produces: thin Click commands with the existing public `main` export.

- [ ] **Step 1: Add a CLI import-boundary test**

Extend `tests/test_architecture_imports.py`:

```python
def test_cli_does_not_import_concrete_infrastructure():
    imports = imports_under(SRC / "interfaces")
    assert not any(name.endswith(("web_search", "local_fs", "llm.client")) for name in imports)
```

- [ ] **Step 2: Add exit-code and compatibility tests**

Assert explicit Workflow dry-run, explicit Agent dry-run, legacy no-subcommand dry-run, invalid mode, and missing county preserve current exit codes and output intent.

- [ ] **Step 3: Move command definitions into interfaces/cli.py**

The new module may import Click, ResearchRequest, normalize_mode, and `create_app_container`; it must not import concrete providers, analyzers, renderers, or storage.

- [ ] **Step 4: Turn top-level cli.py into a compatibility export**

```python
from .interfaces.cli import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run CLI and architecture tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_agent_cli.py tests/test_architecture_imports.py -q
.\.venv\Scripts\python.exe -m county_research_ai.cli workflow -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
.\.venv\Scripts\python.exe -m county_research_ai.cli agent -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
```

- [ ] **Step 6: Commit**

```powershell
git add src/county_research_ai/interfaces src/county_research_ai/cli.py tests/test_cli.py tests/test_agent_cli.py tests/test_architecture_imports.py
git commit -m "refactor: make cli a thin interface"
```

### Task 10: Remove Dead Logic, Document Architecture, and Verify Release

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/superpowers/specs/2026-09-20-research-architecture-optimization-design.md` only if implementation facts require a correction
- Delete: unreachable private Pipeline helpers and duplicated Agent rendering code

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented, statically checked, fully verified research architecture.

- [ ] **Step 1: Find remaining duplicate or forbidden logic**

```powershell
rg -n "get_settings\(|isinstance\(.*SearchCollector|mode ==|mode in \{" src/county_research_ai/application src/county_research_ai/agent src/county_research_ai/pipeline.py
```

Expected: no global Settings reads in application code, no concrete collector checks in Agent Tools, and mode branching restricted to normalization/registry construction.

- [ ] **Step 2: Delete unreachable compatibility internals**

Use `rg` references before deleting each private method. Keep only documented facade methods and attributes required by compatibility tests.

- [ ] **Step 3: Update README architecture and examples**

Document the flow:

```text
CLI → AppContainer → WorkflowRunner / AgentRuntime → ResearchApplication
    → ModeRegistry → Ports → Infrastructure
```

Explain that Workflow and Agent share the same five application use cases and differ only in orchestration.

- [ ] **Step 4: Expand CI type-checking**

Change the mypy step to:

```yaml
- name: Type-check architecture boundaries
  run: python -m mypy src/county_research_ai/domain src/county_research_ai/ports src/county_research_ai/application src/county_research_ai/modes src/county_research_ai/infrastructure src/county_research_ai/reporting
```

- [ ] **Step 5: Run the complete release verification**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/county_research_ai/domain src/county_research_ai/ports src/county_research_ai/application src/county_research_ai/modes src/county_research_ai/infrastructure src/county_research_ai/reporting
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m county_research_ai.cli workflow -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
.\.venv\Scripts\python.exe -m county_research_ai.cli agent -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
git diff --check
```

Expected: every command exits `0`; CLI output identifies Workflow and Agent correctly.

- [ ] **Step 6: Run controlled real-provider smoke tests**

Only when configured credentials are present, run:

```powershell
.\.venv\Scripts\python.exe -m county_research_ai.cli workflow -c 巴中 -f 肉牛产业 --mode snapshot --no-cache
.\.venv\Scripts\python.exe -m county_research_ai.cli agent -c 巴中 -f 肉牛产业 --mode snapshot --max-steps 8 --no-trace
```

Expected: reports are generated with the configured Gemini model. If the provider returns 429/503 after retries, record it as an external availability result rather than a code regression.

- [ ] **Step 7: Commit final cleanup and documentation**

```powershell
git add README.md .github/workflows/ci.yml src tests docs
git commit -m "docs: finalize research application architecture"
```
