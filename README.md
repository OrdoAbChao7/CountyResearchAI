# CountyResearchAI

输入县名与可选的产业方向，采集公开资料并生成带来源链接的县域产业研究初稿。

[![CI](https://github.com/OrdoAbChao7/CountyResearchAI/actions/workflows/ci.yml/badge.svg)](https://github.com/OrdoAbChao7/CountyResearchAI/actions/workflows/ci.yml) ![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)

这是一个研究原型。报告供人工核查和继续研究使用：公开资料的覆盖度取决于地区与搜索服务，模型生成的判断也可能遗漏背景或缺少依据。未配置 API Key 时使用 Mock 数据，只适合验证流程，不能作为研究证据。项目当前的验证边界见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 能做什么

| 模式 | 命令参数 | 研究内容 |
| --- | --- | --- |
| 产业现状 | `snapshot`（默认，`industry` 为别名） | 产业现状、优势、短板和建议 |
| 产业兴衰 | `rise-fall` | 产业起源、扩张、衰退及规律 |
| 长周期历史 | `long-history` | 从县域形成到当代的发展脉络 |

不指定 `--focus` 时，程序会根据检索材料推荐候选产业方向；推荐结果仍需人工确认。固定流程由 Workflow 执行，Agent 模式则在限定步骤内规划工具调用，并可保存 JSON 执行轨迹。两者共用搜索、分析和报告能力。

```mermaid
flowchart TD
    A[县名、方向与模式] --> B[问题树规划 (Question Tree)]
    B --> C[动态多意图检索 (QueryEngine + 消歧)]
    C --> D[结构化事实库 (EvidenceStore)]
    D --> E[反思评价与证据缺口 (ResearchCritic)]
    E -- 存在关键缺口 --> F[定向补充检索 (Supplemental Search)]
    F --> D
    E -- 证据充足 --> G[专业智能体协同分析 (经济/政策/产业)]
    G --> H[事实核验与冲突消解 (FactVerifier)]
    H --> I[Markdown 深度研究报告 (带可信溯源角标)]
```

## 快速开始

需要 Python 3.10 或更高版本。以下命令在 PowerShell 中运行：

```powershell
git clone https://github.com/OrdoAbChao7/CountyResearchAI.git
cd CountyResearchAI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

在 `.env` 中填入 `LLM_API_KEY`，并为选用的搜索服务填写 `TAVILY_API_KEY`、`SERPER_API_KEY` 或 `BING_API_KEY`。模板默认使用 DeepSeek 和 Tavily；更换服务时相应调整 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_MODEL` 和 `SEARCH_PROVIDER`。如需使用 Mock，请把模板中的 `YOUR_...` 占位值清空；空 Key 会启用对应环节的 Mock 实现。

```powershell
county-research -c 安吉县 -f 竹产业
```

报告默认写入 `reports/`；原始资料和处理结果默认写入 `data/`。可通过 `.env` 中的 `REPORTS_DIR` 和 `DATA_DIR` 调整位置，其他运行参数见 [`config/settings.yaml`](config/settings.yaml) 和 [`config/sources.yaml`](config/sources.yaml)。

## 常用命令

```powershell
county-research -c 安吉县                         # 自动发现产业方向
county-research workflow -c 安吉县 -f 竹产业      # 显式使用固定流程
county-research -c 安吉县 -f 竹产业 --deep         # 启用深度多智能体与证据核验研究
county-research -c 鹤岗市 --mode rise-fall
county-research -c 信丰县 --mode long-history
county-research agent -c 安吉县 -f 竹产业 --mode snapshot
county-research agent -c 安吉县 --max-steps 8 --dry-run
```

| 选项 | 用途 |
| --- | --- |
| `-c, --county` | 县名，运行研究时必填 |
| `-f, --focus` | 产业方向；省略时自动发现 |
| `-m, --mode` | 研究模式；默认 `snapshot` |
| `--deep` | 启用深度多智能体协同研究（问题树拆解、Critic反思补检、经济/政策/产业分工及事实核验） |
| `--historical` / `--long-history` | 固定流程中选择对应模式的快捷开关 |
| `--no-cache` | 固定流程中跳过缓存 |
| `--dry-run` | 只检查参数，不运行研究 |

`agent` 另支持 `--max-steps` 和 `--no-trace`。执行轨迹默认保存在 `agent_traces/`。完整参数以 `county-research --help`、`county-research workflow --help` 和 `county-research agent --help` 为准。

## 基准评测 (Benchmark)

项目内置了针对县域产业研究真实质量的客观基准评测系统（`src/county_research_ai/evaluation/`），涵盖安吉县竹产业、信丰县脐橙产业、鹤岗市产业转型三个基准案例。

评测指标涵盖：
- **检索质量**：Precision@K、Recall@K（核心事实覆盖率）、官方权威来源占比、内容去重率；
- **研究深度与可靠性**：关键事实支持率（Claim-Evidence 闭环）、冲突与口径差异检出率。

完整评测报告与数据详见 [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md)。评测复现命令：
```powershell
python -c "from county_research_ai.evaluation.runner import BenchmarkRunner; runner = BenchmarkRunner(); reports = runner.run_all_cases(); [print(r.to_markdown()) for r in reports.values()]"
```

## 代码与验证

核心代码位于 `src/county_research_ai/`：`application/` 编排研究步骤，`modes/` 定义模式，`search/` 和 `llm/` 接入资料与模型，`reporting/` 生成报告，`agent/` 负责 Agent 流程。提示词位于 `prompts/`，测试位于 `tests/`。

```powershell
python -m pip install -e ".[dev]"
python -m pytest --no-cov -q
```

示例初稿见 [`reports/`](reports/)。这些文件展示输出形式，不代表其事实内容已经逐条核实。项目采用 Python、Click、Pydantic、httpx、Jinja2 和兼容 OpenAI API 的模型客户端；依赖清单以 [`pyproject.toml`](pyproject.toml) 为准。

短视频内容与渲染扩展维护在 `codex/video-content` 分支，不属于默认研究流程。
