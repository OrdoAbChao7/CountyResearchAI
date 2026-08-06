# AI县域产业研究助手 (CountyResearchAI)

> 基于 LLM 的自动化县域产业研究工具：输入县名 + 研究方向，自动完成「数据采集 → 结构化处理 → 智能分析 → 报告生成」全流程，产出可读的 Markdown 产业研究报告。

## 核心特性

- **多源数据采集** — 网络搜索 (Tavily/Serper/Bing) + 政府公开数据白名单过滤，可插拔数据源架构
- **LLM 智能分析** — 基于提示词工程，产出产业现状/优势/短板/建议四维结构化洞察 + 执行摘要
- **报告自动生成** — 标准化章节模板，一键输出 Markdown 报告
- **数据可追溯** — raw / processed / report 三层留存，便于复盘与调试
- **配置外置** — YAML 配置 + 环境变量，改配置不动代码
- **接口抽象** — 每层定义抽象基类，替换 LLM / 数据源零成本
- **Mock 降级** — 未配置 API Key 时自动降级为 Mock 数据，链路始终可跑

## 架构概览

```
[用户输入: 县名 + 方向]
        ↓
[search]    多源采集 (Web + Gov 并发)  → data/raw/
        ↓
[storage]   清洗去重 + 缓存复用          → data/processed/
        ↓
[llm]       4 任务分析 + 摘要生成        (调用 prompts/ 模板)
        ↓
[reporting] 章节拼装 + Markdown 渲染     → reports/{县}_{方向}_{日期}.md
```

## 项目结构

```
CountyResearchAI/
├── src/county_research_ai/     # 核心源码
│   ├── search/                 # 数据采集层 (web_search / gov_data / collector)
│   ├── llm/                    # LLM 分析层 (client / analyzer / prompt_loader)
│   ├── storage/                # 存储层 (local_fs)
│   ├── reporting/              # 报告生成层
│   ├── pipeline.py             # 流程编排 + Mock 兜底
│   ├── cli.py                  # 命令行入口 (Click)
│   ├── config.py               # 配置加载 (YAML + .env)
│   ├── models.py               # Pydantic 数据模型
│   └── exceptions.py           # 异常层次
├── config/                     # YAML 配置
│   ├── settings.yaml           # 应用主配置
│   └── sources.yaml            # 政府数据源白名单
├── prompts/                    # LLM 提示词模板 (Jinja2)
├── data/                       # 运行产物 (raw / processed)
├── reports/                    # 生成的报告
├── tests/                      # 单元测试 (130 个，覆盖率 77%)
├── scripts/                    # 验证脚本
└── pyproject.toml
```

## 快速开始

### 1. 环境准备

- Python ≥ 3.10
- 任一 LLM API Key（推荐 DeepSeek，国内访问稳定、性价比高）
- 任一搜索 API Key（推荐 Tavily，专为 AI 优化）

### 2. 安装

```bash
git clone https://github.com/OrdoAbChao7/CountyResearchAI.git
cd CountyResearchAI

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e ".[dev]"
```

### 3. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key（文件已被 `.gitignore` 忽略，不会泄露）：

```dotenv
# ---------- LLM 大模型配置 ----------
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-key        # 必填
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# ---------- 搜索 API 配置 ----------
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-your-tavily-key     # 必填
```

**API Key 获取地址**：

| 服务 | 获取地址 | 说明 |
|------|----------|------|
| DeepSeek | https://platform.deepseek.com/api_keys | 国内访问稳定，性价比高 |
| Tavily | https://app.tavily.com/dashboard/api-key | 专为 AI 优化的搜索 API |
| Serper | https://serper.dev | 基于 Google 的搜索 API |
| Bing | https://www.microsoft.com/en-us/bing/apis/bing-web-search-api | 微软搜索 API |

> **Mock 降级**：如果不配置任何 API Key，Pipeline 会自动降级为 Mock 数据 + Mock LLM，链路仍可完整跑通（报告内容为构造示例，非真实分析）。

### 4. 运行

```bash
# 设置 PYTHONPATH（未 pip install -e . 时需要）
$env:PYTHONPATH="src"          # Windows PowerShell
# export PYTHONPATH=src        # macOS/Linux

# 基础用法
python -m county_research_ai.cli -c 安吉县 -f 竹产业

# 完整选项示例
python -m county_research_ai.cli -c 安吉县 -f 竹产业 --no-cache --log-level INFO
```

报告将生成在 `reports/` 目录下，文件名格式为 `{县名}_{方向}_{日期}.md`。

### CLI 选项

| 选项 | 简写 | 说明 |
|------|------|------|
| `--county` | `-c` | 县名（必填），如 `安吉县` |
| `--focus` | `-f` | 研究方向（必填），如 `竹产业` |
| `--no-cache` | | 跳过缓存，强制重新采集与分析 |
| `--dry-run` | | 仅校验参数并打印预期输出，不执行 Pipeline |
| `--log-level` | | 日志级别：DEBUG / INFO / WARNING / ERROR |

## 配置说明

| 文件 | 作用 |
|------|------|
| `.env` | 敏感信息（API Key），不入库 |
| `config/settings.yaml` | 应用主配置（模型参数、超时、并发、缓存 TTL 等） |
| `config/sources.yaml` | 政府数据源域名白名单与路径关键词 |

### 关键配置项（.env）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `deepseek` | LLM 供应商 |
| `LLM_API_KEY` | （空） | LLM API Key，留空则降级 MockLLM |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_TEMPERATURE` | `0.3` | 生成温度 |
| `LLM_MAX_TOKENS` | `4096` | 单次最大 token |
| `SEARCH_PROVIDER` | `tavily` | 搜索引擎 |
| `TAVILY_API_KEY` | （空） | 搜索 API Key，留空则降级 MockSearch |
| `SEARCH_MAX_RESULTS` | `10` | 单次搜索结果数 |
| `CACHE_TTL_HOURS` | `24` | 缓存有效期（小时） |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 测试

```bash
# 运行全部 130 个单元测试（Mock 外部 API，无需真实 Key）
$env:PYTHONPATH="src"
python -m pytest --no-cov -q

# 查看覆盖率详情
python -m pytest --cov=county_research_ai --cov-report=term-missing --cov-report=html:htmlcov
```

HTML 覆盖率报告生成在 `htmlcov/index.html`。

## 运行产物

```
data/raw/{县名}/{日期}/raw_docs.json      # 原始采集文档
data/processed/{县名}/{方向}.json          # 清洗后结构化数据
reports/{县名}_{方向}_{日期}.md            # 最终研究报告
```

## 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.10+ |
| LLM 客户端 | openai SDK（兼容 DeepSeek / Qwen / OpenAI） |
| 数据校验 | Pydantic v2 |
| CLI | Click |
| HTTP | httpx |
| 模板 | Jinja2 |
| 重试 | tenacity |
| HTML 解析 | beautifulsoup4 |
| 测试 | pytest + pytest-cov |

## MVP 边界

当前版本 (v0.1) **刻意做减法**：

- 单县单次研究（不支持多县对比）
- Markdown 输出（暂不导出 PDF / HTML）
- 本地文件系统存储（暂不引入数据库）
- CLI 交互（暂不做 Web UI）
- 单线程 Pipeline（暂不引入多 Agent）

## License

MIT
