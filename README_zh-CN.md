<div align="center">
  <h1>CountyResearchAI</h1>
  <a href="./README.md"><b>English</b></a> | <b>中文</b>
</div>
<br>

# AI县域产业研究助手 (CountyResearchAI)

> 基于 LLM 的自动化县域产业研究工具：输入县名（可选研究方向），自动完成「数据采集 → 产业方向识别 → 结构化处理 → 智能分析 → 报告生成」全流程，产出可读的 Markdown 产业研究报告。支持三种研究模式：**snapshot**（产业现状快照）、**rise-fall**（产业兴衰规律研究）、**long-history**（县域长周期兴衰史分析）。

## 核心特性

- **三研究模式** — `snapshot` 产业现状四维分析（现状/优势/短板/建议）；`rise-fall` 县域产业兴衰规律研究（起家→壮大→衰落→规律归纳），回答 7 个核心问题；`long-history` 县域长周期兴衰史分析（建县→地理→传统→近代→计划经济→改革开放→当代），回答"这个县为什么形成？靠什么存在？如何兴起？为何衰落？未来是否可能重新激活？"
- **产业方向自动发现** — 只给县名也能跑：先搜索该县相关资料，由 LLM 识别 3-5 个候选重点产业并选出置信度最高的方向
- **多源数据采集** — 网络搜索 (Tavily/Serper/Bing) + 政府公开数据白名单过滤，可插拔数据源架构；rise-fall 模式启用 10 条近现代产业兴衰查询；long-history 模式启用 10 条数百年长周期史料查询（建县沿革/县志/驿道水运/人口迁徙/国营工厂/行政区划等）
- **LLM 智能分析** — 基于提示词工程，snapshot 产出四维结构化洞察 + 执行摘要；rise-fall 产出时间线/起家产业/兴衰因子/人才流失/兴衰模型归纳；long-history 产出历史阶段/地理逻辑/传统经济/近代冲击/计划经济/改革开放/当代视角/长周期模型归纳
- **报告自动生成** — 标准化章节模板，一键输出 Markdown 报告（snapshot 6 章节 / rise-fall 9 节 / long-history 9 节固定结构）
- **数据可追溯** — raw / processed / report 三层留存，关键结论绑定证据 URL，便于复盘与调试
- **配置外置** — YAML 配置 + 环境变量，改配置不动代码
- **接口抽象** — 每层定义抽象基类，替换 LLM / 数据源零成本
- **Mock 降级** — 未配置 API Key 时自动降级为 Mock 数据，链路始终可跑

## 架构概览

```
[用户输入: 县名] + (可选) 研究方向 + 研究模式(--mode)
        ↓
        ├──── snapshot 模式（默认）─────────────────────┐
        │                                              ↓
        │  [search]    多源采集 (Web + Gov 并发)        → data/raw/
        │       ↓
        │  [discover]  产业方向自动识别 (仅当未指定 --focus)
        │       ↓
        │  [storage]   清洗去重 + 缓存复用              → data/processed/
        │       ↓
        │  [llm]       4 任务分析 + 摘要生成
        │       ↓
        │  [reporting] 章节拼装 + Markdown 渲染         → reports/{县}_{方向}_{日期}.md
        │
        ├──── rise-fall 模式（--mode rise-fall）────────┐
        │                                               ↓
        │  [search]    近现代产业兴衰采集 (10 条查询)    → data/raw/
        │       ↓
        │  [storage]   清洗去重 + 缓存复用               → data/processed/
        │       ↓
        │  [rise-fall] 时间线→起家→兴起→衰落→人才→模型→摘要 (7 任务)
        │       ↓
        │  [reporting] 9 节兴衰规律报告渲染              → reports/{县}_兴衰规律_{日期}.md
        │
        └──── long-history 模式（--mode long-history）──┐
                                                        ↓
           [search]    长周期史料采集 (10 条建县/县志/驿道/人口/国营/区划查询) → data/raw/
                ↓
           [storage]   清洗去重 + 缓存复用               → data/processed/
                ↓
           [long-history] 阶段→地理→传统→近代→计划→改革→当代→模型→摘要 (9 任务)
                ↓
           [reporting] 9 节长周期兴衰史报告渲染           → reports/{县}_长周期兴衰史_{日期}.md
```

**三种使用方式**：

| 模式 | 命令 | 适用场景 |
|------|------|---------|
| 指定方向 | `cli -c 安吉县 -f 竹产业` | 已知研究方向，直接深入分析（snapshot） |
| 自动发现 | `cli -c 安吉县` | 不熟悉该县，由系统识别重点产业（snapshot） |
| 兴衰规律 | `cli -c 鹤岗市 --mode rise-fall` | 研究县域产业兴衰历史规律（rise-fall） |
| 长周期史 | `cli -c 信丰县 --mode long-history` | 研究县域数百年兴衰史与长周期规律（long-history） |

## 项目结构

```
CountyResearchAI/
├── src/county_research_ai/     # 核心源码
│   ├── search/                 # 数据采集层 (web_search / gov_data / collector)
│   │                           #   collector 支持 mode 参数,三种模式启用不同查询模板
│   ├── llm/                    # LLM 分析层
│   │   ├── analyzer.py         #   snapshot 模式: 4 任务分析 + discover_focus
│   │   ├── rise_fall_analyzer.py # rise-fall 模式: 7 任务兴衰规律分析
│   │   ├── long_history_analyzer.py # long-history 模式: 9 任务长周期兴衰史分析
│   │   ├── client.py           #   OpenAI 兼容客户端
│   │   └── prompt_loader.py    #   Jinja2 模板加载
│   ├── storage/                # 存储层 (local_fs)
│   ├── reporting/              # 报告生成层
│   │   ├── renderer.py         #   snapshot 模式渲染器
│   │   ├── rise_fall_renderer.py # rise-fall 模式渲染器 (9 节固定结构)
│   │   ├── long_history_renderer.py # long-history 模式渲染器 (9 节固定结构)
│   │   └── templates/          #   report / rise_fall / long_history 模板
│   ├── pipeline.py             # 流程编排 + Mock 兜底 + 模式路由
│   ├── cli.py                  # 命令行入口 (Click, --mode 参数)
│   ├── config.py               # 配置加载 (YAML + .env)
│   ├── models.py               # Pydantic 数据模型 (含兴衰规律 6 + 长周期 4 模型)
│   └── exceptions.py           # 异常层次
├── config/                     # YAML 配置
│   ├── settings.yaml           # 应用主配置
│   └── sources.yaml            # 政府数据源白名单
├── prompts/                    # LLM 提示词模板 (Jinja2)
│   ├── discovery.md            # 产业方向自动识别模板
│   ├── industry_analysis.md    # 产业现状分析模板
│   ├── recommendations.md      # 发展建议模板
│   ├── summary.md              # 执行摘要模板
│   ├── timeline_extraction.md  # [rise-fall] 历史时间线提取
│   ├── origin_industry.md      # [rise-fall] 起家产业识别
│   ├── rise_analysis.md        # [rise-fall] 兴起因子分析
│   ├── decline_analysis.md     # [rise-fall] 衰落因子分析
│   ├── talent_loss.md          # [rise-fall] 人才流失分析
│   ├── historical_pattern.md   # [rise-fall] 兴衰模型归纳
│   ├── rise_fall_summary.md    # [rise-fall] 执行摘要
│   ├── long_history_periods.md # [long-history] 历史阶段提取
│   ├── geo_origin_analysis.md  # [long-history] 建县与地理逻辑
│   ├── traditional_economy.md  # [long-history] 传统时代生存方式
│   ├── modern_shocks.md        # [long-history] 近代冲击与变迁
│   ├── state_period.md         # [long-history] 计划经济时期再组织
│   ├── reform_period.md        # [long-history] 改革开放产业重塑
│   ├── contemporary_long_view.md # [long-history] 新世纪长周期视角
│   ├── long_history_pattern.md # [long-history] 长周期兴衰模型归纳
│   └── long_history_summary.md # [long-history] 执行摘要
├── data/                       # 运行产物 (raw / processed)
├── reports/                    # 生成的报告
├── tests/                      # 单元测试
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
LLM_API_KEY=YOUR_LLM_API_KEY             # 必填
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# ---------- 搜索 API 配置 ----------
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=YOUR_TAVILY_API_KEY       # 必填
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

# 方式一：指定研究方向（快速深入分析，snapshot 模式）
python -m county_research_ai.cli -c 安吉县 -f 竹产业

# 方式二：自动识别产业方向（不熟悉该县时推荐，snapshot 模式）
python -m county_research_ai.cli -c 安吉县
# 系统会先搜索该县资料 → LLM 识别 3-5 个候选产业 → 选定置信度最高的方向

# 方式三：产业兴衰规律研究（rise-fall 模式）
python -m county_research_ai.cli -c 鹤岗市 --mode rise-fall
# 研究该县产业起家→壮大→衰落→规律,产出 9 节兴衰规律报告
# 等价快捷写法:
python -m county_research_ai.cli -c 鹤岗市 --historical

# 方式四：县域长周期兴衰史分析（long-history 模式）
python -m county_research_ai.cli -c 信丰县 --mode long-history
# 研究该县建县→地理→传统→近代→计划经济→改革开放→当代,产出 9 节长周期兴衰史报告
# 等价快捷写法:
python -m county_research_ai.cli -c 信丰县 --long-history

# 完整选项示例
python -m county_research_ai.cli -c 安吉县 -f 竹产业 --no-cache --log-level INFO
```

报告将生成在 `reports/` 目录下：
- snapshot 模式：`{县名}_{方向}_{日期}.md`
- rise-fall 模式：`{县名}_兴衰规律_{日期}.md`
- long-history 模式：`{县名}_长周期兴衰史_{日期}.md`

### CLI 选项

| 选项 | 简写 | 必填 | 说明 |
|------|------|------|------|
| `--county` | `-c` | 是 | 县名，如 `安吉县` |
| `--focus` | `-f` | 否 | 研究方向，如 `竹产业`。**留空则自动识别该县重点产业**（snapshot 模式） |
| `--mode` | `-m` | 否 | 研究模式：`snapshot`（默认，产业现状快照）/ `rise-fall`（产业兴衰规律研究）/ `long-history`（县域长周期兴衰史分析） |
| `--historical` | | | `rise-fall` 模式快捷开关（等价于 `--mode rise-fall`） |
| `--long-history` | | | `long-history` 模式快捷开关（等价于 `--mode long-history`） |
| `--no-cache` | | | 跳过缓存，强制重新采集与分析 |
| `--dry-run` | | | 仅校验参数并打印预期输出，不执行 Pipeline |
| `--log-level` | | | 日志级别：DEBUG / INFO / WARNING / ERROR |

### rise-fall 模式详解

`rise-fall` 模式研究县域产业兴衰历史规律，回答 7 个核心问题：

1. **县域基本画像** — 当前产业阶段、壮大期产业、关键事件数
2. **靠什么起家** — 早期立县之本（起家产业 + 主导时期 + 机制说明）
3. **为什么能发展** — 3-6 个兴起因子（资源禀赋/政策红利/区位/人力/市场等）
4. **靠什么创收壮大** — 壮大期扩张事件 + 形成规模的产业方向
5. **何时拐点** — 5-15 个关键时间线事件（起家/扩张/拐点/衰落/政策/外部冲击）
6. **为什么衰败** — 2-5 个衰落因子（含严重程度评分 0-1）
7. **属于哪种兴衰模型** — 归类为 8 种典型模型之一（资源诅咒/政策驱动/市场周期/产业转移/人才流失/路径锁定/多元共生/混合型）

**报告结构（9 节固定）**：执行摘要 / 一、县域基本画像 / 二、起家产业 / 三、兴起逻辑 / 四、壮大机制 / 五、关键拐点 / 六、衰落机制 / 七、人才流失分析 / 八、县域兴衰模型归纳 / 九、结论

**兴衰模型类型**：

| 模型 | 说明 |
|------|------|
| `resource_curse` | 资源诅咒型（资源起家→枯竭→衰退，如鹤岗、玉门） |
| `policy_driven` | 政策驱动型（红利期繁荣→政策退坡→转型） |
| `market_cycle` | 市场周期型（随宏观周期与价格周期起伏） |
| `industry_transfer` | 产业转移型（承接→壮大→再转移出） |
| `talent_drain` | 人才流失型（产业基础尚可但人力持续外流） |
| `path_lock` | 路径锁定型（单一产业过度依赖，转型困难） |
| `diversified_growth` | 多元共生型（多产业协同，韧性较强） |
| `mixed` | 混合型（上述多种模型叠加） |

### long-history 模式详解

`long-history` 模式研究县域长周期兴衰史，从数百年尺度回答"这个县为什么形成？靠什么存在？如何兴起？为何衰落？未来是否可能重新激活？"等核心问题。

**研究维度（6 个连续历史阶段）**：

1. **建县与地理逻辑** — 建县动因、地理格局、交通区位、资源条件等深层结构因子
2. **传统时代生存方式** — 建县至近代的农业/手工业/商贸经济基础
3. **近代冲击与变迁** — 近代战争、交通变革、市场冲击对县域的影响
4. **计划经济时期再组织** — 1949-1978 国营工厂、集体化、行政重塑
5. **改革开放后的产业重塑** — 1978 后产业转型、市场化、城镇化
6. **新世纪以来发展变化** — 2000 至今人口迁徙、交通升级、产业升级、边缘化或再激活

**报告结构（9 节固定）**：执行摘要 / 一、长周期总论 / 二、建县与地理逻辑 / 三、传统时代生存方式 / 四、近代冲击与变迁 / 五、计划经济时期再组织 / 六、改革开放后的产业重塑 / 七、新世纪以来发展变化 / 八、长周期兴衰模型 / 九、历史规律总结

**长周期兴衰模型类型**：

| 模型 | 说明 |
|------|------|
| `agricultural_hinterland` | 农业腹地型（农业资源禀赋支撑长期稳定，但上限受限） |
| `transport_corridor` | 交通通道型（因交通要道而兴衰，随技术迭代重估） |
| `resource_frontier` | 资源边疆型（资源开发起家，随资源枯竭或替代而衰退） |
| `administrative_center` | 行政中心型（行政层级稳定性决定县域命运） |
| `policy_reactivation` | 政策再激活型（国家政策干预在关键节点重塑轨迹） |
| `border_trade` | 边贸枢纽型（因边境贸易而兴，随政治经济格局变化而衰） |
| `cultural_industry` | 文化产业型（依托历史文化资源形成特色产业） |
| `mixed` | 混合型（上述多种模型叠加） |

### snapshot 与 rise-fall 与 long-history 的边界

| 维度 | snapshot | rise-fall | long-history |
|------|----------|-----------|--------------|
| 焦点 | 产业现状 | 近现代产业周期 | 县域数百年命运 |
| 时间尺度 | 当下 | 近 30-50 年 | 数百年（建县至今） |
| 核心问题 | 现状/优势/短板/建议 | 起家→壮大→衰落→规律 | 为何形成/靠什么存在/如何兴起/为何衰落/能否再激活 |
| 搜索查询 | 通用产业查询 | 10 条近现代产业兴衰查询 | 10 条建县/县志/驿道/人口/国营/区划查询 |
| 报告章节 | 6 章节 | 9 节 | 9 节 |
| 模型归纳 | 无 | 8 种产业兴衰模型 | 8 种长周期兴衰模型 |

三种模式互相独立，互不破坏，可根据研究目的选择。

### 自动发现工作原理

当 `--focus` 未指定时，系统会执行以下流程：

1. 用县名构造通用搜索查询（如"安吉县 产业 发展现状"），多源采集文档
2. 将搜索结果摘要喂给 LLM，配合 [prompts/discovery.md](file:///e:/CountyResearchAI/prompts/discovery.md) 模板
3. LLM 返回 JSON：3-5 个候选产业 + 置信度 + 判断依据 + 选定方向
4. 用选定的方向继续后续 Process → Analyze → Report 流程

**降级策略**：
- LLM 调用失败 → 返回通用候选（特色农业/乡村旅游/先进制造业）
- 搜索结果为空 → 降级为"特色农业"
- 解析失败 → 兜底"特色农业"

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
# 运行全部单元测试（Mock 外部 API，无需真实 Key）
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
reports/{县名}_{方向}_{日期}.md            # snapshot 模式研究报告
reports/{县名}_兴衰规律_{日期}.md          # rise-fall 模式研究报告
reports/{县名}_长周期兴衰史_{日期}.md      # long-history 模式研究报告
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

当前版本 (v0.3) **刻意做减法**：

- 单县单次研究（不支持多县对比）
- Markdown 输出（暂不导出 PDF / HTML）
- 本地文件系统存储（暂不引入数据库）
- CLI 交互（暂不做 Web UI）
- 单线程 Pipeline（暂不引入多 Agent）

> v0.3 新增 `long-history` 模式：县域长周期兴衰史分析（建县→地理→传统→近代→计划经济→改革开放→当代→长周期模型归纳），与 v0.2 的 `rise-fall` 模式和 v0.1 的 `snapshot` 模式共存。

## License

MIT
