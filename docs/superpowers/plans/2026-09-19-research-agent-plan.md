# County Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ( - [ ] ) syntax for tracking.

**Goal:** 在不破坏现有研究 Pipeline 和内容生产命令的前提下，新增一个可解释、可测试、可追踪的 Plan-and-Execute Research Agent。

**Architecture:** 新增 agent 包，使用 Pydantic AgentState 传递单次运行状态；Planner 生成结构化工具动作；ToolRegistry 限制可执行工具；AgentRuntime 负责规划、执行、观察和停止；Verifier 检查中间结果和最终报告；TraceStore 保存可回放的执行轨迹。研究工具通过适配器复用现有搜索、处理、分析、渲染组件。

**Tech Stack:** Python 3.10+, Pydantic v2, Click, 现有 LLMClient, pytest, Ruff, 本地 JSON / Markdown 存储。

**Spec:** docs/superpowers/specs/2026-09-19-research-agent-design.md

## Global Constraints

- 保留现有默认研究命令、content、story 和 topic 命令的行为。
- 不覆盖或回退工作区中用户已有的未提交改动。
- 首期 Agent 只接入研究链路，内容生产链路保持独立。
- Planner 只能选择 ToolRegistry 中的工具，不执行任意代码。
- 单次 Agent 运行最多执行 8 步，CLI 可通过 --max-steps 覆盖。
- 不保存 API Key；Trace 默认保存摘要，不保存未经截断的 Prompt 或完整 LLM 原始响应。
- 新增测试不得依赖真实搜索 API 或真实 LLM。
- 现有测试必须继续通过。

## Review Focus

- Planner 返回非法 JSON 或未知工具时，Agent 是否记录错误并最终有界退出，而不是执行任意动作或死循环；对应 Task 3 和 Task 5 测试。
- 无 focus 的请求是否只在已有搜索结果后调用 discover_focus，并将 fallback focus 写回状态；对应 Task 3 和 Task 4 测试。
- 工具部分成功或抛出异常时，Trace 是否保留工具名、理由、错误和已完成中间结果；对应 Task 5 测试。
- Planner 宣布 finish 但没有报告、章节或证据时，Verifier 是否拒绝成功；对应 Task 3 和 Task 5 测试。
- 新 CLI 子命令是否不会破坏现有 Click group 的默认研究路径，dry-run 是否不写报告和 Trace；对应 Task 6 测试。

## 文件结构

新增 Agent 核心文件：

- src/county_research_ai/agent/__init__.py：公开 Agent Runtime、工厂和核心模型。
- src/county_research_ai/agent/models.py：状态、计划动作、工具结果、观察记录、错误和运行结果模型。
- src/county_research_ai/agent/base.py：Planner、Tool、Verifier、TraceStore 的协议与基础接口。
- src/county_research_ai/agent/registry.py：工具注册、查找和工具描述。
- src/county_research_ai/agent/planner.py：LLM Planner、fallback planner 和结构化动作解析。
- src/county_research_ai/agent/tools.py：研究工具适配器和工具工厂。
- src/county_research_ai/agent/verifier.py：步骤和最终结果校验。
- src/county_research_ai/agent/trace.py：Trace 构造与 JSON 落盘。
- src/county_research_ai/agent/runtime.py：Plan-and-Execute 主循环。
- src/county_research_ai/agent/factory.py：根据现有默认 Pipeline 装配 Agent。
- prompts/agent_planner.md：Planner 的结构化 JSON 输出模板。

新增测试文件：

- tests/test_agent_models.py
- tests/test_agent_registry.py
- tests/test_agent_planner.py
- tests/test_agent_tools.py
- tests/test_agent_verifier.py
- tests/test_agent_runtime.py
- tests/test_agent_cli.py

修改文件：

- src/county_research_ai/cli.py：新增 agent 子命令，保留当前未提交内容命令改动。
- README.md：增加 Agent 架构、运行命令和边界说明。
- README_AI.md：更新 AI 上下文中的文件地图和 Agent 调用链。

---

### Task 1: 建立 Agent 状态和领域模型

**Files:**
- Create: src/county_research_ai/agent/__init__.py
- Create: src/county_research_ai/agent/models.py
- Create: tests/test_agent_models.py

**Interfaces:**

- Consumes: ResearchRequest、RawDoc、ProcessedData、DiscoveryResult、AnalysisResult、CountyRiseFallAnalysis、CountyLongHistoryAnalysis、ResearchReport。
- Produces: AgentStatus、ToolStatus、AgentPlanStep、AgentError、AgentObservation、AgentState、AgentTrace、AgentRunResult。

- [ ] Step 1: Write the failing model tests

~~~python
from county_research_ai.agent.models import AgentPlanStep, AgentState, AgentStatus
from county_research_ai.models import ResearchRequest


def test_agent_state_starts_pending_with_request():
    state = AgentState.from_request(
        ResearchRequest(county="安吉县", focus="竹产业", mode="snapshot")
    )
    assert state.status == AgentStatus.PENDING
    assert state.request.county == "安吉县"
    assert state.steps_used == 0
    assert state.raw_docs == []


def test_plan_step_requires_tool_and_reason():
    step = AgentPlanStep(
        tool="search_materials",
        reason="需要先收集资料",
        arguments={"county": "安吉县"},
    )
    assert step.tool == "search_materials"
    assert step.is_final is False


def test_state_apply_patch_rejects_unknown_fields():
    state = AgentState.from_request(ResearchRequest(county="安吉县"))
    try:
        state.apply_patch({"not_allowed": "value"})
    except ValueError as exc:
        assert "not_allowed" in str(exc)
    else:
        raise AssertionError("unknown state patch should fail")
~~~

- [ ] Step 2: Run the focused tests to verify they fail

Run: pytest tests/test_agent_models.py -q

Expected: FAIL because the agent package and model classes do not exist.

- [ ] Step 3: Implement the typed state models

Implement AgentPlanStep with tool, reason, arguments, is_final and planner_source fields; AgentObservation with step index, tool, status, reason, summaries, error and elapsed time; and AgentState with request, status, plan, counters, raw docs, discovery, processed data, three mode-specific analysis fields, report, report_path, observations and errors.

AgentState.from_request creates a pending state. AgentState.apply_patch only permits raw_docs, discovery, processed, the three analysis fields, report, report_path and status; unknown fields raise ValueError.

- [ ] Step 4: Run the focused tests to verify they pass

Run: pytest tests/test_agent_models.py -q

Expected: PASS.

- [ ] Step 5: Commit the isolated model layer

~~~bash
git add src/county_research_ai/agent tests/test_agent_models.py
git commit -m "feat: add agent state models"
~~~

### Task 2: 定义工具协议和注册表

**Files:**
- Create: src/county_research_ai/agent/base.py
- Create: src/county_research_ai/agent/registry.py
- Create: tests/test_agent_registry.py

**Interfaces:**

- Consumes: AgentState and AgentPlanStep from Task 1.
- Produces: ToolSpec、ToolResult、AgentTool、ToolRegistry、AgentToolError。

- [ ] Step 1: Write failing registry tests

Create an EchoTool fixture with name, description, spec() and execute(). Assert that registration, lookup, deterministic description ordering, duplicate rejection and unknown-tool rejection all work.

- [ ] Step 2: Run the focused tests to verify they fail

Run: pytest tests/test_agent_registry.py -q

Expected: FAIL because the registry interfaces do not exist.

- [ ] Step 3: Implement the tool protocol and registry

Use a runtime-checkable Protocol:

~~~python
class AgentTool(Protocol):
    name: str
    description: str

    def spec(self) -> ToolSpec: ...
    def execute(self, state: AgentState, arguments: dict[str, Any]) -> ToolResult: ...
~~~

ToolRegistry.register rejects duplicate names; get raises AgentToolError for unknown names; describe returns deterministic name-sorted ToolSpec objects for stable Planner prompts and tests.

- [ ] Step 4: Run the focused tests to verify they pass

Run: pytest tests/test_agent_registry.py -q

Expected: PASS.

- [ ] Step 5: Commit the tool boundary

~~~bash
git add src/county_research_ai/agent/base.py src/county_research_ai/agent/registry.py tests/test_agent_registry.py
git commit -m "feat: add agent tool registry"
~~~

### Task 3: 实现 Planner 和 Verifier

**Files:**
- Create: src/county_research_ai/agent/planner.py
- Create: src/county_research_ai/agent/verifier.py
- Create: prompts/agent_planner.md
- Create: tests/test_agent_planner.py
- Create: tests/test_agent_verifier.py

**Interfaces:**

- Consumes: AgentState、AgentPlanStep、LLMClient、PromptLoader、ToolRegistry from Tasks 1–2。
- Produces: Planner、LLMPlanner、FallbackPlanner、VerificationResult、AgentVerifier。

- [ ] Step 1: Write Planner and Verifier failing tests

Test plain JSON parsing, fenced JSON parsing, malformed JSON fallback, fallback planner ordering, no-focus discovery insertion, unknown-tool validation, and final verification failure when the report is absent.

- [ ] Step 2: Run focused tests to verify they fail

Run: pytest tests/test_agent_planner.py tests/test_agent_verifier.py -q

Expected: FAIL because Planner and Verifier are not implemented.

- [ ] Step 3: Add the Planner prompt and parser

prompts/agent_planner.md must require exactly one JSON object with tool, reason, arguments and is_final, and include the available tool specs, compact state summary and remaining step count.

Implement:

~~~python
class Planner(Protocol):
    def next_step(self, state: AgentState, tool_specs: list[ToolSpec]) -> AgentPlanStep: ...


class FallbackPlanner:
    def next_step(self, state, tool_specs) -> AgentPlanStep: ...


class LLMPlanner:
    def __init__(self, llm: LLMClient, prompt_loader: PromptLoader | None = None): ...
    def next_step(self, state, tool_specs) -> AgentPlanStep: ...
~~~

FallbackPlanner selects the first unmet prerequisite: search_materials; discover_focus when focus is empty and raw docs exist; build_evidence_pack; analyze_research; render_report; finish.

LLMPlanner parses plain and fenced JSON. On LLM, parse or schema failure it returns the validated fallback action with planner_source="fallback"; it never returns an unvalidated action.

- [ ] Step 4: Implement step and final verification

Implement VerificationResult with ok, fatal, code and message, plus AgentVerifier.verify_step and verify_final.

verify_final checks report path existence, county and focus in report text, at least one source URL or explicit data-insufficient marker, and no fatal errors. verify_step checks the expected state field for each known tool and records tool errors as non-success observations unless marked fatal.

- [ ] Step 5: Run focused tests to verify they pass

Run: pytest tests/test_agent_planner.py tests/test_agent_verifier.py -q

Expected: PASS.

- [ ] Step 6: Commit Planner and Verifier

~~~bash
git add src/county_research_ai/agent/planner.py src/county_research_ai/agent/verifier.py prompts/agent_planner.md tests/test_agent_planner.py tests/test_agent_verifier.py
git commit -m "feat: add agent planner and verifier"
~~~

### Task 4: 将现有研究能力封装为 Agent Tools

**Files:**
- Create: src/county_research_ai/agent/tools.py
- Create: tests/test_agent_tools.py

**Interfaces:**

- Consumes: ResearchPipeline、existing analyzers、renderer、storage、AgentState and ToolResult.
- Produces: SearchMaterialsTool、FocusDiscoveryTool、EvidencePackTool、ResearchAnalysisTool、ReportTool、build_research_tools().

- [ ] Step 1: Write tool-level failing tests

Inject MockSearchProvider, MockLLMClient, LocalFSStorage configured to tmp_path, and existing analyzers/renderers. Test that search writes raw docs, discovery writes selected focus, evidence builds ProcessedData, analysis dispatches all three modes, and report persists to the injected reports directory.

- [ ] Step 2: Run focused tests to verify they fail

Run: pytest tests/test_agent_tools.py -q

Expected: FAIL because the tool adapters do not exist.

- [ ] Step 3: Implement an injected research tool context

Define:

~~~python
@dataclass(frozen=True)
class ResearchToolContext:
    pipeline: ResearchPipeline
    processor: DocumentProcessor
    settings: Settings
~~~

Each tool returns a ToolResult with a bounded observation and only the state fields it owns. The adapters may call existing stage behavior through one narrow internal adapter; they must not duplicate Prompt logic or instantiate a second LLM client.

Implement updates: search to raw_docs; discovery to discovery and normalized request.focus; evidence to processed plus raw/processed storage; analysis to exactly one mode-specific analysis field; report to report and report_path.

For report rendering, reuse existing mode-specific renderers and the same filename template as ResearchPipeline. Keep ResearchReport as the compatibility object returned to CLI and Verifier.

- [ ] Step 4: Run focused tests to verify they pass

Run: pytest tests/test_agent_tools.py -q

Expected: PASS.

- [ ] Step 5: Commit the research tool adapters

~~~bash
git add src/county_research_ai/agent/tools.py tests/test_agent_tools.py
git commit -m "feat: expose research pipeline as agent tools"
~~~

### Task 5: 实现 Runtime、Trace 和运行结果

**Files:**
- Create: src/county_research_ai/agent/trace.py
- Create: src/county_research_ai/agent/runtime.py
- Create: tests/test_agent_runtime.py

**Interfaces:**

- Consumes: Planner、ToolRegistry、AgentVerifier、research tools and Agent models from Tasks 1–4。
- Produces: TraceStore、JsonTraceStore、AgentRuntime.run() and deterministic end-to-end Agent behavior。

- [ ] Step 1: Write runtime failing tests

Test a Mock snapshot run, no-focus discovery, max-step failure, repeated unknown-tool failure, tool exception capture, and trace persistence. Assert the normal observation order is search_materials, build_evidence_pack, analyze_research, render_report, finish.

- [ ] Step 2: Run focused tests to verify they fail

Run: pytest tests/test_agent_runtime.py -q

Expected: FAIL because Runtime and TraceStore are not implemented.

- [ ] Step 3: Implement trace persistence

Implement:

~~~python
class TraceStore(Protocol):
    def save(self, trace: AgentTrace) -> Path: ...


class JsonTraceStore:
    def __init__(self, root: Path): ...
    def save(self, trace: AgentTrace) -> Path: ...
~~~

Write UTF-8 JSON with model_dump_json(indent=2), create parent directories idempotently, use a safe county path, and never serialize secrets.

- [ ] Step 4: Implement the bounded Plan-and-Execute loop

Implement:

~~~python
class AgentRuntime:
    def __init__(
        self,
        *,
        planner: Planner,
        registry: ToolRegistry,
        verifier: AgentVerifier,
        trace_store: TraceStore | None = None,
        max_steps: int = 8,
    ) -> None: ...

    def run(self, request: ResearchRequest) -> AgentRunResult: ...
~~~

The loop creates state, asks for one action, records it before execution, rejects unknown tools, catches tool exceptions, applies only validated patches, verifies every step, verifies finish before completion, fails on max steps or fatal errors, and saves a trace unless disabled.

Do not repeat a failed finish action forever. After one failed final verification, pass the failure summary to the next Planner call and terminate if no unmet transition remains.

- [ ] Step 5: Run focused and full tests

Run: pytest tests/test_agent_runtime.py -q

Expected: PASS.

Run: pytest --no-cov -q

Expected: all existing tests and Agent tests PASS.

- [ ] Step 6: Commit Runtime and Trace

~~~bash
git add src/county_research_ai/agent/trace.py src/county_research_ai/agent/runtime.py tests/test_agent_runtime.py
git commit -m "feat: add bounded agent runtime and traces"
~~~

### Task 6: 装配 Agent 并接入 CLI

**Files:**
- Create: src/county_research_ai/agent/factory.py
- Modify: src/county_research_ai/agent/__init__.py
- Modify: src/county_research_ai/cli.py
- Create: tests/test_agent_cli.py

**Interfaces:**

- Consumes: create_default_pipeline(), AgentRuntime, JsonTraceStore and research tools from Tasks 1–5。
- Produces: create_default_agent(), county-research agent CLI command。

- [ ] Step 1: Write CLI failing tests

Use CliRunner to test agent dry-run with no outputs, Mock run with report and trace, max-steps forwarding, failure exit code, and the existing default invocation without a subcommand.

- [ ] Step 2: Run focused CLI tests to verify they fail

Run: pytest tests/test_agent_cli.py -q

Expected: FAIL because the agent command and factory do not exist.

- [ ] Step 3: Implement the factory

Implement:

~~~python
def create_default_agent(
    *,
    max_steps: int = 8,
    save_trace: bool = True,
    trace_root: Path | None = None,
) -> AgentRuntime: ...
~~~

The factory calls create_default_pipeline() once, passes its selected dependencies into ResearchToolContext, registers the five tools, selects LLMPlanner when an LLM API key exists and FallbackPlanner otherwise, and uses JsonTraceStore under PROJECT_ROOT / "agent_traces" by default.

- [ ] Step 4: Add the Click subcommand without changing default behavior

Add required county, optional focus, mode choices snapshot/rise-fall/long-history, max-steps with minimum 1 and default 8, no-trace and dry-run. The command builds ResearchRequest, calls the factory, prints mode and output paths, returns exit code 0 only for completed runs, and maps failed runs to exit code 1. Dry-run must not construct or call the Agent.

- [ ] Step 5: Run focused and regression tests

Run: pytest tests/test_agent_cli.py tests/test_cli.py -q

Expected: PASS.

- [ ] Step 6: Commit factory and CLI integration

~~~bash
git add src/county_research_ai/agent/factory.py src/county_research_ai/agent/__init__.py src/county_research_ai/cli.py tests/test_agent_cli.py
git commit -m "feat: add agent cli mode"
~~~

### Task 7: 更新文档并完成交付验证

**Files:**
- Modify: README.md
- Modify: README_AI.md
- No changes: current user-owned content files unless a regression requires a narrowly scoped compatibility fix

- [ ] Step 1: Add public Agent usage documentation

Document:

~~~powershell
$env:PYTHONPATH = "src"
python -m county_research_ai.cli agent -c 安吉县 -f 竹产业 --mode snapshot
~~~

Add a Mermaid diagram showing CLI → AgentRuntime → Planner → ToolRegistry → Tools → Verifier → Report + Trace, and distinguish the Agent layer from the existing deterministic research Pipeline.

- [ ] Step 2: Add the interview-facing design explanation

Explain why Plan-and-Execute is used instead of free ReAct; how the five tools map to existing components; how state and observations are serialized; how max steps and verification prevent silent failure; why Mock mode proves control flow but not factual correctness; and why multi-agent collaboration and arbitrary code execution are non-goals.

- [ ] Step 3: Run static checks and all tests

Run:

~~~powershell
$env:PYTHONPATH = "src"
python -m pytest --no-cov -q
ruff check src tests
python scripts/_verify_imports.py
~~~

Expected: all tests pass, Ruff exits 0, and import verification exits 0.

- [ ] Step 4: Run a temporary-directory Mock Agent smoke test

Construct create_default_agent(trace_root=<tmp_path>) with existing Mock dependencies and run ResearchRequest(county="安吉县", focus="竹产业"). Verify the state is completed, the report contains county and focus, the trace JSON contains expected tool observations, no external API request is made, and existing user-owned content files are unchanged.

- [ ] Step 5: Inspect the final diff and report handoff

Run:

~~~bash
git status --short
git diff --stat HEAD~6..HEAD
git log --oneline -8
~~~

Confirm Agent commits contain only planned files, all tests pass, and user-owned pre-existing changes remain uncommitted and untouched.
