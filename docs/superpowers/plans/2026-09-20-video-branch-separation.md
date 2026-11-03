# Video Branch Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve all short-video content and rendering source on `codex/video-content`, while leaving `master` with only county research Workflow and Agent capabilities.

**Architecture:** Create a recoverable source checkpoint on the dedicated video branch before deleting anything. Bring the same checkpoint back to `master`, remove the video/content surface there, and verify each branch against its own product contract.

**Tech Stack:** Git, Python 3.13, Click, Pydantic v2, pytest, Ruff, mypy, Remotion/TypeScript on the video branch.

**Spec:** `docs/superpowers/specs/2026-09-20-video-branch-separation-design.md`

## Global Constraints

- Preserve Gemini configuration, Agent reliability fixes, long-history renderer fixes, and explicit `workflow` / `agent` CLI entries on both branches.
- Never commit `.env`, API keys, `node_modules/`, `video_template/out/`, `content_outputs/`, generated media, or Agent traces.
- Do not use `git reset --hard`, `git clean`, or an overwrite checkout.
- Do not delete an untracked video source file until it is present in a commit reachable from `codex/video-content`.
- Keep existing report, data, and trace paths unchanged.

## Review Focus

- Mixed `cli.py` changes: `workflow` and `agent` must remain on `master` while `content`, `story`, `topic`, and `video` are removed.
- Mixed `models.py` changes: research models must remain importable while all content/video models disappear from `master`.
- Untracked source versus generated output: TypeScript source and public media assets are preserved; dependencies and renders are ignored.
- Branch recoverability: every deleted master file must be retrievable from `codex/video-content`.
- CLI contract: legacy no-subcommand Workflow invocation must continue to work after pruning.

---

### Task 1: Ignore Generated Video and Runtime Artifacts

**Files:**
- Modify: `.gitignore`
- Test: Git ignore checks from the repository root

**Interfaces:**
- Consumes: existing repository ignore rules.
- Produces: ignore rules used by the source checkpoint task.

- [ ] **Step 1: Verify the generated paths are currently visible to Git**

Run:

```powershell
git check-ignore -q agent_traces/sample.json
git check-ignore -q content_outputs/sample.json
git check-ignore -q video_template/node_modules/sample.js
git check-ignore -q video_template/out/sample.png
```

Expected: each command returns exit code `1`, proving the new rules do not exist yet.

- [ ] **Step 2: Add explicit ignore rules**

Append this exact block to `.gitignore`:

```gitignore
# ===== Agent 与视频运行产物 =====
agent_traces/
content_outputs/
video_template/node_modules/
video_template/out/
video_template/.remotion/
*.mp4
*.srt
```

- [ ] **Step 3: Verify the ignore rules**

Run:

```powershell
git check-ignore agent_traces/sample.json content_outputs/sample.json video_template/node_modules/sample.js video_template/out/sample.png
```

Expected: all four paths are printed.

- [ ] **Step 4: Run the current full Python suite before branching**

Run:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all currently collected tests pass.

- [ ] **Step 5: Commit the ignore boundary**

```powershell
git add .gitignore
git commit -m "chore: ignore video runtime artifacts"
```

### Task 2: Create the Recoverable Video Source Branch

**Files:**
- Track: current modified research files
- Track: `src/county_research_ai/content/**`
- Track: `src/county_research_ai/video/**`
- Track: content prompts and verification script
- Track: `tests/test_video_pipeline.py`, `tests/test_video_tts.py`
- Track: `video_template` source/config/public assets, excluding ignored paths

**Interfaces:**
- Consumes: ignore boundary from Task 1 and the complete dirty working tree.
- Produces: branch `codex/video-content` with a source checkpoint commit.

- [ ] **Step 1: Create the branch without discarding the working tree**

```powershell
git switch -c codex/video-content
```

Expected: `git branch --show-current` prints `codex/video-content`.

- [ ] **Step 2: Stage all source-level work**

```powershell
git add -A
git status --short
```

Expected: source, tests, prompts, documentation, and template source are staged; `.env`, `agent_traces`, `content_outputs`, `video_template/node_modules`, and `video_template/out` are absent.

- [ ] **Step 3: Assert generated paths are not staged**

Run:

```powershell
$staged = git diff --cached --name-only
$forbidden = $staged | Select-String -Pattern '(^|/)(\.env|agent_traces|content_outputs|node_modules|out)(/|$)|\.(mp4|srt)$'
if ($forbidden) { $forbidden; exit 1 }
```

Expected: exit code `0` with no output.

- [ ] **Step 4: Commit the complete recoverable source state**

```powershell
git commit -m "feat: preserve video content branch"
```

- [ ] **Step 5: Verify the video branch contains every required source area**

Run:

```powershell
git ls-tree -r --name-only HEAD -- src/county_research_ai/content src/county_research_ai/video prompts video_template tests | Select-String -Pattern 'content/|video/|content_director|short_video_script|video_template/src|test_video'
```

Expected: matches are printed for both Python packages, prompts, template source, and video tests.

### Task 3: Verify the Video Branch Product

**Files:**
- Test: `tests/test_video_pipeline.py`
- Test: `tests/test_video_tts.py`
- Test: existing content and CLI tests

**Interfaces:**
- Consumes: committed video branch source.
- Produces: evidence that the branch can reconstruct and run its content/video product.

- [ ] **Step 1: Verify Python content and video imports**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -c "from county_research_ai.content import ContentPipeline; from county_research_ai.video import VideoPipeline; print('video imports ok')"
```

Expected: `video imports ok`.

- [ ] **Step 2: Run video-focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_video_pipeline.py tests/test_video_tts.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run the complete video-branch Python suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Verify CLI commands**

```powershell
.\.venv\Scripts\python.exe -m county_research_ai.cli --help
```

Expected: output contains `workflow`, `agent`, `content`, `story`, `topic`, and `video`.

- [ ] **Step 5: Verify template reproducibility without committing dependencies**

```powershell
Test-Path video_template\package.json
Test-Path video_template\package-lock.json
git ls-files video_template/node_modules video_template/out content_outputs agent_traces
```

Expected: both `Test-Path` calls return `True`; `git ls-files` prints nothing.

### Task 4: Bring the Source Checkpoint to Master and Pin the Pruned Contract

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_models.py`
- Create: `tests/test_default_branch_scope.py`

**Interfaces:**
- Consumes: tip commit of `codex/video-content`.
- Produces: failing tests that define the video-free `master` contract.

- [ ] **Step 1: Switch to master and copy the source checkpoint**

```powershell
git switch master
git cherry-pick codex/video-content
```

Expected: `master` contains all current fixes and video source before pruning; no working source is lost.

- [ ] **Step 2: Add a failing CLI scope test**

Add to `tests/test_cli.py`:

```python
def test_default_cli_only_exposes_research_commands():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "workflow" in result.output
    assert "agent" in result.output
    for command in ("content", "story", "topic", "video"):
        assert command not in result.output
```

- [ ] **Step 3: Add a failing model-scope test**

Add to `tests/test_models.py`:

```python
def test_default_models_do_not_export_video_content_types():
    import county_research_ai.models as models

    for name in (
        "ContentAngle", "ScriptSegment", "VideoScript", "FactCheckItem",
        "FactCheckResult", "StoryLine", "TopicCandidate", "ContentPackage",
    ):
        assert not hasattr(models, name)
```

- [ ] **Step 4: Add a failing filesystem scope test**

Create `tests/test_default_branch_scope.py`:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_branch_has_no_video_product_source():
    forbidden = [
        PROJECT_ROOT / "src/county_research_ai/content",
        PROJECT_ROOT / "src/county_research_ai/video",
        PROJECT_ROOT / "video_template",
        PROJECT_ROOT / "scripts/_verify_content.py",
    ]
    assert [str(path) for path in forbidden if path.exists()] == []
```

- [ ] **Step 5: Run the new tests and verify they fail for the intended reason**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py::test_default_cli_only_exposes_research_commands tests/test_models.py::test_default_models_do_not_export_video_content_types tests/test_default_branch_scope.py -q
```

Expected: failures name the still-present commands, models, and source directories.

### Task 5: Remove Video and Content Product Code from Master

**Files:**
- Modify: `src/county_research_ai/cli.py`
- Modify: `src/county_research_ai/models.py`
- Delete: `src/county_research_ai/content/**`
- Delete: `src/county_research_ai/video/**`
- Delete: content/video prompts, tests, scripts, and `video_template/**`

**Interfaces:**
- Consumes: failing scope tests from Task 4.
- Produces: video-free default branch while preserving research imports and commands.

- [ ] **Step 1: Remove content/video command definitions and help text**

Delete the complete Click command blocks for `content`, `video`, `story`, and `topic` from `src/county_research_ai/cli.py`. Keep `main`, `workflow_command`, `agent_command`, `_run_research`, `Path`, and the research imports. Change the module and group descriptions to `AI 县域产业研究助手`.

- [ ] **Step 2: Remove content/video model classes**

Delete `models.py` content beginning at the marker:

```python
# ===== 内容生产(短视频脚本流水线) =====
```

Keep every class through `CountyLongHistoryAnalysis` unchanged.

- [ ] **Step 3: Delete the tracked video-only source paths**

Run only after confirming Task 2's branch commit exists:

```powershell
git rm -r src/county_research_ai/content src/county_research_ai/video video_template
git rm prompts/content_director.md prompts/fact_check.md prompts/short_video_script.md prompts/story_mining.md prompts/topic_selection.md
git rm scripts/_verify_content.py tests/test_video_pipeline.py tests/test_video_tts.py
```

Expected: Git stages only the named deletions.

- [ ] **Step 4: Remove local generated directories from the master working tree**

Resolve and inspect each target before deletion:

```powershell
$targets = @(
  (Resolve-Path -LiteralPath 'content_outputs' -ErrorAction SilentlyContinue),
  (Resolve-Path -LiteralPath 'video_template' -ErrorAction SilentlyContinue)
) | Where-Object { $_ -ne $null }
$targets | ForEach-Object { $_.Path }
```

After confirming every printed path starts with `E:\Projects\CountyResearchAI\`, remove only those exact generated directories:

```powershell
$targets | ForEach-Object { Remove-Item -LiteralPath $_.Path -Recurse -Force }
```

- [ ] **Step 5: Run the new scope tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py::test_default_cli_only_exposes_research_commands tests/test_models.py::test_default_models_do_not_export_video_content_types tests/test_default_branch_scope.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the product boundary**

```powershell
git add src/county_research_ai/cli.py src/county_research_ai/models.py tests/test_cli.py tests/test_models.py tests/test_default_branch_scope.py
git commit -m "refactor: remove video product from default branch"
```

### Task 6: Update Default-Branch Documentation and Verify Both Branches

**Files:**
- Modify: `README.md`
- Modify: CLI docstrings in `src/county_research_ai/cli.py`
- Test: all remaining tests and static checks

**Interfaces:**
- Consumes: video-free master from Task 5.
- Produces: documented, verified branch boundary.

- [ ] **Step 1: Remove video product documentation from master**

Make README describe only county research, Workflow, Agent, three modes, reports, traces, configuration, and tests. Add one sentence linking the optional product branch:

```markdown
短视频内容与视频渲染扩展维护在 `codex/video-content` 分支，不属于默认研究产品。
```

- [ ] **Step 2: Scan for forbidden default-branch references**

```powershell
rg -n "ContentPipeline|VideoPipeline|短视频|Remotion|TTS|content_outputs|video_template|county-research (content|video|story|topic)" src tests prompts README.md scripts
```

Expected: no product-code matches; the single branch-note sentence may match `短视频`.

- [ ] **Step 3: Run default CLI smoke tests**

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m county_research_ai.cli workflow -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
.\.venv\Scripts\python.exe -m county_research_ai.cli agent -c 巴中 -f 肉牛产业 --mode snapshot --dry-run
```

Expected: both commands exit `0` and identify their execution mode.

- [ ] **Step 4: Run all default-branch checks**

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/county_research_ai/reporting
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit docs and verification changes**

```powershell
git add README.md src/county_research_ai/cli.py
git commit -m "docs: define research-only default branch"
```

- [ ] **Step 6: Verify the video branch remains recoverable**

```powershell
git ls-tree -r --name-only codex/video-content -- src/county_research_ai/content src/county_research_ai/video video_template | Select-Object -First 20
git log --oneline --decorate -3 master
git log --oneline --decorate -3 codex/video-content
```

Expected: video source appears only in the dedicated branch tree; both branch tips and their purpose are visible.
