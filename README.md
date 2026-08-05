# AI县域产业研究助手 (CountyResearchAI)

> 基于 LLM 的自动化县域产业研究工具:输入县名 + 研究方向,自动完成「数据采集 → 结构化处理 → 智能分析 → 报告生成」全流程,产出可读的 Markdown 产业研究报告。

## ✨ 核心特性

- 🔍 **多源数据采集** — 网络搜索 + 政府公开数据,可插拔数据源架构
- 🧠 **LLM 智能分析** — 基于提示词工程,产出产业现状/优势/短板/建议结构化洞察
- 📄 **报告自动生成** — 标准化章节模板,一键输出 Markdown 报告
- 💾 **数据可追溯** — raw / processed / report 三层留存,便于复盘与调试
- ⚙️ **配置外置** — YAML 配置 + 环境变量,改配置不动代码
- 🔌 **接口抽象** — 每层定义抽象基类,替换 LLM / 数据源零成本

## 🏗️ 架构概览

```
[用户输入:县名+方向]
        ↓
[search]   采集 → data/raw/
        ↓
[storage]  清洗 → data/processed/
        ↓
[llm]      分析(调用 prompts/)
        ↓
[reporting] 渲染 → reports/xxx_产业研究.md
```

详见 [docs/architecture.md](docs/architecture.md)。

## 📁 项目结构

```
CountyResearchAI/
├── src/county_research_ai/     # 核心源码
│   ├── search/                 # 数据采集层
│   ├── llm/                    # LLM 分析层
│   ├── reporting/              # 报告生成层
│   ├── storage/                # 存储层
│   ├── pipeline.py             # 流程编排
│   ├── cli.py                  # 命令行入口
│   ├── config.py               # 配置加载
│   └── models.py               # 数据模型
├── config/                     # YAML 配置
├── prompts/                    # LLM 提示词模板
├── data/                       # 数据(raw/processed)
├── reports/                    # 生成的报告
├── tests/                      # 测试
├── scripts/                    # 运维脚本
└── docs/                       # 文档
```

## 🚀 快速开始

### 1. 环境准备

- Python ≥ 3.10
- 任一 LLM API Key(推荐 DeepSeek,性价比高)
- 任一搜索 API Key(推荐 Tavily,专为 AI 优化)

### 2. 安装

```bash
# 克隆项目
git clone <repo-url> CountyResearchAI
cd CountyResearchAI

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 安装(含开发依赖)
pip install -e ".[dev]"
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env,填入 LLM_API_KEY 和搜索 API Key
```

### 4. 运行

```bash
# 基础用法
county-research --county "安吉县" --focus "竹产业"

# 或通过 Python 模块
python -m county_research_ai --county "安吉县" --focus "竹产业"
```

报告将生成在 `reports/` 目录下。

## ⚙️ 配置说明

| 文件 | 作用 |
|------|------|
| `.env` | 敏感信息(API Key),不入库 |
| `config/settings.yaml` | 应用主配置(模型、超时、并发等) |
| `config/sources.yaml` | 数据源清单与白名单 |

## 🧪 测试

```bash
# 运行全部单元测试(mock 外部 API)
pytest

# 查看覆盖率
pytest --cov-report=html
start htmlcov\index.html       # Windows
```

## 📐 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.10+ |
| LLM 客户端 | openai (兼容 DeepSeek/Qwen) |
| 数据校验 | Pydantic v2 |
| CLI | Click |
| HTTP | httpx |
| 模板 | Jinja2 |
| 测试 | pytest + pytest-mock |
| 代码风格 | Ruff |

## 📌 MVP 边界

当前版本(v0.1)**刻意做减法**:

- ✅ 单县单次研究(不支持多县对比)
- ✅ Markdown 输出(暂不导出 PDF/HTML)
- ✅ 本地文件系统存储(暂不引入数据库)
- ✅ CLI 交互(暂不做 Web UI)
- ✅ 单线程 Pipeline(暂不引入多 Agent)

后续演进路线见 [docs/architecture.md](docs/architecture.md)。

## 📄 License

MIT
