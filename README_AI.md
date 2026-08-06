# CountyResearchAI - AI 上下文简报

> 本文件为 AI Agent 快速理解项目而设，内容精炼、结构化。人类用户请阅读 README.md。

## 项目概述

AI 县域产业研究助手：用户输入「县名 + 可选研究方向」，系统自动完成 **数据采集 → (可选)产业方向识别 → 结构化处理 → LLM 智能分析 → 报告生成**，输出 Markdown 产业研究报告（含执行摘要、产业现状、优势、短板、建议、数据来源 6 章节）。

**核心价值**：
- 产业方向自动发现（`--focus` 可选，未指定时由 LLM 识别）
- 零配置 Mock 降级（无 API Key 也能跑通全链路）
- 可插拔数据源与 LLM
- 数据三层留存（raw/processed/report）便于复盘

## 技术栈

| 类别 | 选型 | 备注 |
|------|------|------|
| 语言 | Python 3.10+ | src layout |
| LLM | openai SDK | 兼容 DeepSeek/Qwen/OpenAI |
| 数据校验 | Pydantic v2 | 含 DiscoveryResult/DiscoveryCandidate |
| CLI | Click | `--focus` 可选 |
| HTTP | httpx | 搜索 API 调用 |
| 模板 | Jinja2 | 提示词 + 文件名渲染 |
| 重试 | tenacity | 网络请求容错 |
| HTML 解析 | beautifulsoup4 | 政府页面正文提取 |
| 配置 | pyyaml + python-dotenv | YAML + .env |
| 测试 | pytest + pytest-cov | 150 个测试，覆盖率 77% |

## 文件地图

```
src/county_research_ai/
├── cli.py              # [入口] Click 命令行，--focus 可选，解析参数 + dry-run + 异常处理
├── pipeline.py         # [编排] 五阶段 Pipeline(含 _stage_discover) + Mock 降级
├── config.py           # [配置] YAML + .env 合并，单例 get_settings/reset_settings
├── models.py           # [模型] Pydantic: CountyInfo/RawDoc/ProcessedData/AnalysisResult
│                       #         DiscoveryCandidate/DiscoveryResult/ResearchReport
├── exceptions.py       # [异常] 层次: CountyResearchAIError → ConfigError/SearchError/LLMError/PipelineError
│
├── search/             # [采集层]
│   ├── base.py         # SearchProvider 抽象基类
│   ├── web_search.py   # Tavily/Serper/Bing 三 provider (include_raw_content=True)
│   ├── gov_data.py     # 政府白名单过滤 + 详情页抓取 (BeautifulSoup)
│   └── collector.py    # SearchCollector: 多查询并发 + _dedup_and_rank 粗排
│                       #   collect() 支持空 focus (自动发现阶段)
│
├── storage/            # [存储层]
│   ├── base.py         # Storage 抽象基类
│   └── local_fs.py     # LocalFSStorage: raw/processed/report 落盘 + 缓存 TTL
│
├── llm/                # [分析层]
│   ├── base.py         # LLMClient 抽象基类
│   ├── client.py       # OpenAICompatibleClient (真实 HTTP 客户端)
│   ├── prompt_loader.py # PromptLoader: Jinja2 模板加载/渲染
│   └── analyzer.py     # LLMAnalyzer: 4 任务串行分析 + generate_summary
│                       #   + discover_focus() 产业方向自动发现
│
└── reporting/          # [报告层] 占位模块，渲染逻辑目前在 pipeline._render_markdown

config/
├── settings.yaml       # 应用主配置 (模型参数/超时/并发/缓存 TTL)
└── sources.yaml        # 政府数据源域名白名单 + 路径关键词

prompts/
├── discovery.md        # 产业方向自动识别模板 (输出 JSON: candidates + selected_focus)
├── industry_analysis.md # 产业现状分析模板
├── recommendations.md   # 发展建议模板
└── summary.md          # 执行摘要模板

data/                   # 运行产物 (gitignore)
├── raw/{县名}/{日期}/raw_docs.json
└── processed/{县名}/{方向}.json

reports/                # 生成的报告 (gitignore)
└── {县名}_{方向}_{日期}.md

tests/                  # 单元测试 (150 个)
├── conftest.py         # 共享 fixtures: MockLLM 支持 discovery 关键词检测
├── test_models.py      # 数据模型测试 (含 DiscoveryCandidate/DiscoveryResult)
├── test_exceptions.py  # 异常层次测试
├── test_config.py      # 配置加载测试
├── test_storage.py     # LocalFSStorage 测试
├── test_search_web.py  # Web 搜索 provider 测试
├── test_search_gov.py  # 政府数据 provider 测试
├── test_search_collector.py # SearchCollector 测试
├── test_llm_prompt_loader.py # PromptLoader 测试
├── test_llm_analyzer.py # LLMAnalyzer 测试 (含 TestDiscoverFocus 8 个)
├── test_pipeline.py    # Pipeline 集成测试 (含 TestPipelineDiscovery 4 个)
└── test_cli.py         # CLI 集成测试 (含 TestCLINoFocus 3 个)
```

## 运行命令

```powershell
# Windows PowerShell
$env:PYTHONPATH="src"
# 如遇代理导致 httpx 失败，清空代理
$env:ALL_PROXY=""

# 方式一：指定研究方向
python -m county_research_ai.cli -c 安吉县 -f 竹产业

# 方式二：自动识别产业方向（推荐用于不熟悉的县）
python -m county_research_ai.cli -c 安吉县

# 完整选项
python -m county_research_ai.cli -c 安吉县 -f 竹产业 --no-cache --log-level DEBUG

# dry-run (不执行 Pipeline)
python -m county_research_ai.cli -c 安吉县 --dry-run
```

报告输出路径: `reports/{县名}_{方向}_{日期}.md`

## 测试命令

```powershell
# 运行全部单元测试 (Mock 外部 API，无需真实 Key)
$env:PYTHONPATH="src"
python -m pytest --no-cov -q

# 查看覆盖率
python -m pytest --cov=county_research_ai --cov-report=term-missing --cov-report=html:htmlcov

# 单测单个模块
python -m pytest tests/test_pipeline.py -v --no-cov

# 仅跑 discovery 相关测试
python -m pytest tests/test_llm_analyzer.py::TestDiscoverFocus tests/test_pipeline.py::TestPipelineDiscovery tests/test_cli.py::TestCLINoFocus -v --no-cov
```

**注意**: `--no-cov` 可跳过 pytest-cov（如未安装）。conftest.py 已在 sys.path 注入 src/，无需 `pip install -e .`。

## Mock 降级逻辑（create_default_pipeline）

Pipeline 组件按 **三级降级策略** 自动选择实现：

| 组件 | 有 API Key | 无 API Key |
|------|-----------|-----------|
| Storage | LocalFSStorage（始终） | LocalFSStorage（始终） |
| Search | SearchCollector（Web+Gov 并发） | MockSearchProvider（3 条构造示例文档） |
| LLM | OpenAICompatibleClient（真实调用） | MockLLMClient（返回构造分析文本，支持 discovery） |

判断逻辑：
- `TAVILY_API_KEY`/`SERPER_API_KEY`/`BING_API_KEY` 任一非空 → 真实 SearchCollector
- `LLM_API_KEY` 非空 → 真实 OpenAICompatibleClient
- Key 存在但初始化失败 → 降级 Mock + WARNING 日志

**Discovery 降级**：
- 搜索结果为空 → `_fallback_discovery()` 返回 3 个通用候选（特色农业/乡村旅游/先进制造业）
- LLM 调用失败 → 同上
- JSON 解析失败 → 返回空候选 + `selected_focus=""`
- Pipeline 层兜底：`selected_focus` 为空 → 降级为"特色农业"

## 已知问题

1. **MockStorage 死代码** — `pipeline.py` 中 `MockStorage` 类不再被 `create_default_pipeline` 使用，仅测试引用。可考虑删除。
2. **pipeline.py 死代码** — `_build_analysis_prompt` 和 `_build_summary` 静态方法已被 `LLMAnalyzer` 内部实现取代。
3. **跳转链接未过滤** — Tavily 返回的 `/goto?url=CAES...` 相对路径未被过滤，出现在数据来源中。

## 已修复 Bug

1. **`pipeline.py` L34** — `LLMError` 未 import，真实 LLM 调用时抛 `NameError`
2. **`pipeline.py` L120-124** — `--no-cache` 不生效：cli 把 `no_cache` 放进 `request.options`，但 `pipeline.run` 只读 `settings.cache.ttl_hours`，忽略 options。修复：读 `request.options.get("no_cache")`，为 True 时 `cache_hours=0`
3. **`conftest.py` L42-55** — 测试依赖 `.env` 真实 key：autouse fixture 只 `reset_settings()`，但 `get_settings()` 重载时 `load_dotenv(.env)` 把真实 key 注入。修复：monkeypatch `load_dotenv` 为空操作 + 清掉环境变量中的 API key
4. **`web_search.py` L112** — Tavily `include_raw_content=False` 导致 content 全为空。修复：改为 `True` + `_parse_results` 始终填充 content（优先 raw_content，退化 snippet）

## Pipeline 核心流程

```
CLI 入口 (--focus 可选)
  │
  ├─ dry-run? → 打印预期路径 → exit 0
  │
  ├─ create_default_pipeline()  ← 三级 Mock 降级
  │
  └─ pipeline.run(request)
       │
       ├─ Stage1: _stage_search()
       │   └─ SearchCollector.collect()  (focus 为空时用县名构造查询)
       │       ├─ Web Provider (Tavily/Serper/Bing)
       │       └─ Gov Provider (白名单过滤)
       │       → list[RawDoc]
       │
       ├─ Stage1.5: _stage_discover()  (仅当 request.focus 为空)
       │   └─ LLMAnalyzer.discover_focus()
       │       ├─ _render_search_results() 渲染搜索摘要
       │       ├─ LLM chat (discovery.md 模板) → JSON
       │       └─ _parse_discovery_response() → DiscoveryResult
       │       → focus = discovery.selected_focus (失败降级 "特色农业")
       │
       ├─ Stage2: _stage_process()
       │   ├─ 缓存命中? → 直接返回
       │   └─ URL 去重 + 统计 total_chars
       │       → save_raw() + save_processed()
       │       → ProcessedData
       │
       ├─ Stage3: _stage_analyze()
       │   └─ LLMAnalyzer.analyze()
       │       ├─ industry_status → LLM chat
       │       ├─ advantages     → LLM chat
       │       ├─ shortcomings   → LLM chat
       │       └─ recommendations → LLM chat
       │       → list[AnalysisResult]
       │
       ├─ Stage4: _stage_report()
       │   ├─ generate_summary() → LLM chat (第5次，或第6次如果走了 discovery)
       │   ├─ 拼装 6 章节 ReportSection
       │   ├─ _render_markdown() → Markdown 字符串
       │   └─ save_report() → reports/{县}_{方向}_{日期}.md
       │
       └─ 返回 (ResearchReport, Path)
```

## 关键配置 (.env)

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 空 | 留空降级 MockLLM |
| `LLM_PROVIDER` | `deepseek` | 可选: deepseek/qwen/openai |
| `LLM_MODEL` | `deepseek-chat` | |
| `TAVILY_API_KEY` | 空 | 留空降级 MockSearch |
| `SEARCH_PROVIDER` | `tavily` | 可选: tavily/serper/bing |
| `CACHE_TTL_HOURS` | `24` | 缓存有效期 |
| `LOG_LEVEL` | `INFO` | |

## Discovery 关键代码位置

| 位置 | 职责 |
|------|------|
| [models.py](file:///e:/CountyResearchAI/src/county_research_ai/models.py) | `DiscoveryCandidate`、`DiscoveryResult` 数据模型 |
| [analyzer.py](file:///e:/CountyResearchAI/src/county_research_ai/llm/analyzer.py) `discover_focus()` | 主入口：渲染搜索结果 → 调 LLM → 解析 JSON |
| [analyzer.py](file:///e:/CountyResearchAI/src/county_research_ai/llm/analyzer.py) `_parse_discovery_response()` | JSON 解析（含正则提取 + 容错） |
| [analyzer.py](file:///e:/CountyResearchAI/src/county_research_ai/llm/analyzer.py) `_fallback_discovery()` | 降级：返回通用候选 |
| [pipeline.py](file:///e:/CountyResearchAI/src/county_research_ai/pipeline.py) `_stage_discover()` | Pipeline 阶段 1.5 |
| [pipeline.py](file:///e:/CountyResearchAI/src/county_research_ai/pipeline.py) `run()` L117-148 | focus 为空时触发发现 + 兜底逻辑 |
| [prompts/discovery.md](file:///e:/CountyResearchAI/prompts/discovery.md) | LLM 提示词模板（要求输出 JSON） |
| [cli.py](file:///e:/CountyResearchAI/src/county_research_ai/cli.py) | `--focus` 改为可选 |
