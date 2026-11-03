# 视频能力分支隔离设计

## 目标

将短视频内容生产和视频渲染能力保留在专用分支 `codex/video-content`，同时让默认分支 `master` 回归纯县域研究产品。默认分支只提供 Workflow、Agent、搜索、证据处理、研究分析和 Markdown 报告，不包含短视频策划、脚本、音频、视频渲染或剪辑模板。

本次拆分必须保留当前已完成的非视频改动，包括 Gemini 配置兼容、Agent 可靠性修复、长历史报告修复，以及显式的 `workflow` / `agent` 两级 CLI 入口。

## 当前状态

当前分支为 `master`。工作区同时包含两类尚未提交的变更：

1. 县域研究核心改动：Agent Planner 和工具约束、长历史分析与报告修复、Workflow CLI、静态检查和回归测试。
2. 视频产品改动：短视频内容生产、故事线、选题、事实核查、TTS、图片准备、Remotion、剪映草稿、视频模板及相关 CLI 和模型。

视频相关文件大多尚未被 Git 跟踪，且 `cli.py` 与 `models.py` 同时包含研究核心和视频功能，不能直接按目录删除或简单切换分支。

## 目标分支结构

```text
master
└── 县域研究产品
    ├── workflow
    ├── agent
    ├── search / processor / llm / reporting / storage
    └── Markdown 报告

codex/video-content
├── master 的县域研究能力
├── content / story / topic
├── video / TTS / image / Remotion / draft
├── 短视频提示词与内容模型
├── 视频模板源码
└── 视频与内容生产测试
```

`codex/video-content` 从拆分时的 `master` 创建，作为视频能力的长期承载分支。后续默认分支中的通用研究修复需要按需合并或 cherry-pick 到视频分支，视频专属提交不合并回默认分支。

## 默认分支保留范围

`master` 保留：

- `workflow` 和 `agent` CLI；
- `snapshot`、`rise-fall`、`long-history` 三种研究模式；
- 搜索、政府数据采集、证据处理、LLM 分析、报告渲染和本地存储；
- Agent Planner、Tool Registry、Runtime、Verifier 和 Trace；
- 研究领域模型、研究提示词和研究测试；
- Gemini/OpenAI 兼容 LLM 配置；
- 当前已完成的长历史 Renderer 修复和 Agent 模式兜底。

默认分支删除：

- `content`、`video`、`story`、`topic` CLI 命令；
- `src/county_research_ai/content/`；
- `src/county_research_ai/video/`；
- `models.py` 中短视频内容、脚本、事实核查和内容包模型；
- `prompts/content_director.md`、`fact_check.md`、`short_video_script.md`、`story_mining.md`、`topic_selection.md`；
- 视频和内容生产专属测试、验证脚本；
- `video_template/`；
- `content_outputs/`、模板构建产物和预览文件。

## 视频分支保留范围

`codex/video-content` 保留：

- 默认分支的全部研究能力；
- ContentPipeline、StoryMiner、TopicAgent、ContentDirector、ScriptGenerator 和 FactChecker；
- VideoPipeline、TTSGenerator、ImageGenerator、RemotionRenderer 和 DraftGenerator；
- `content`、`story`、`topic`、`video` CLI；
- 内容与视频领域模型；
- 内容生产提示词；
- Python 视频测试和内容验证脚本；
- `video_template` 的 TypeScript/TSX 源码、配置、`package.json` 和锁文件。

视频分支不提交可重建或运行生成的数据：

- `video_template/node_modules/`；
- `video_template/out/`；
- `content_outputs/`；
- 生成的 MP4、音频、字幕、图片、剪映草稿和测试截图。

视频分支需要通过 `.gitignore` 明确排除这些生成物。

## 拆分策略

为避免混合工作区中的改动丢失，拆分按以下顺序进行：

1. 对当前工作区进行只读清单检查，确认研究核心、视频源码和生成物的精确路径。
2. 创建 `codex/video-content`，在该分支提交当前研究核心和视频源码；生成物不进入提交。
3. 验证视频分支能够导入内容和视频模块，并运行对应测试。
4. 切回 `master`，将需要保留的研究核心改动同步到默认分支。
5. 在 `master` 删除视频专属模块、CLI、模型、提示词、测试、模板和生成物。
6. 更新默认分支 README、CLI 帮助和测试预期，使产品定位只描述县域研究。
7. 在两个分支分别运行验证，确认默认分支无视频引用，视频分支仍可使用完整视频链路。

拆分过程中不使用 `git reset --hard`、`git clean` 或覆盖式 checkout。所有删除都针对已核对的具体视频路径；重要源码必须先在视频分支形成可恢复提交。

## CLI 契约

默认分支顶层命令只保留：

```text
workflow
agent
```

兼容旧的无子命令 Workflow 调用：

```powershell
python -m county_research_ai.cli -c 巴中 -f 肉牛产业 --mode snapshot
```

推荐显式入口：

```powershell
python -m county_research_ai.cli workflow -c 巴中 -f 肉牛产业 --mode snapshot
python -m county_research_ai.cli agent -c 巴中 -f 肉牛产业 --mode snapshot
```

视频分支继续提供：

```text
workflow
agent
content
story
topic
video
```

## 模型边界

默认分支的 `models.py` 只保留研究请求、原始文档、处理数据、研究分析和研究报告模型。以下模型只存在于视频分支：

- `ContentAngle`；
- `ScriptSegment`；
- `VideoScript`；
- `FactCheckItem`；
- `FactCheckResult`；
- `StoryLine`；
- `TopicCandidate`；
- `ContentPackage`；
- 视频包内的音频和渲染结果模型。

此次拆分不顺带重构研究模型文件；研究架构优化将在视频能力移出默认分支后另行设计，避免同时进行两种高风险变更。

## 文档与依赖

默认分支 README 删除短视频脚本和视频渲染的功能描述、命令示例和输出目录说明。视频分支 README 保留完整说明，并明确它是带视频扩展的产品分支。

若视频依赖仅由视频模块使用，应只出现在视频分支。默认分支不保留 Node/Remotion、TTS、音视频处理相关依赖。研究核心已有依赖保持不变。

## 验证要求

### 默认分支

- `python -m county_research_ai.cli --help` 只显示 `workflow` 和 `agent`；
- `rg` 检查 `src/`、`tests/`、`prompts/` 和 README 中不存在视频功能引用；
- Workflow dry-run 成功；
- Agent dry-run 成功；
- 全部默认分支测试通过；
- Ruff 和现有类型检查通过；
- 实际 Gemini 配置和 `.env` 不进入提交或输出。

### 视频分支

- CLI 显示研究、内容和视频命令；
- 内容与视频模块可导入；
- Python 内容/视频测试通过；
- Remotion 模板源码完整，依赖可通过锁文件重新安装；
- `node_modules`、渲染产物和 `content_outputs` 未被 Git 跟踪。

## 风险与控制

### 混合文件误删

`cli.py` 和 `models.py` 同时包含研究与视频代码。删除必须按命令块和模型块进行，并用默认分支测试证明研究入口未受影响。

### 未跟踪源码丢失

视频源码当前多数未被 Git 跟踪。任何默认分支删除之前，必须先确认这些源码已经进入 `codex/video-content` 的提交。

### 分支长期漂移

视频分支不会自动获得默认分支后续修复。通用修复需要通过小型、可审查的 cherry-pick 或合并同步，避免重新把视频代码带回默认分支。

### 生成物体积

`node_modules` 和渲染输出体积大且可重建，不纳入版本控制。源码保留不等于保存本地构建缓存或生成结果。

## 完成标准

- `codex/video-content` 存在且包含可恢复的视频与内容生产源码提交；
- `master` 不包含视频/内容生产模块、命令、模型、提示词、测试或模板；
- `master` 保留 Workflow、Agent、三种研究模式及此前修复；
- 两个分支均通过各自范围内的验证；
- 工作区中不存在因拆分而遗失但未明确归类的源码；
- 默认分支产品文档与实际 CLI 一致。
