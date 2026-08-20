<div align="center">
  <h1>CountyResearchAI</h1>
  **English** | [**中文**](./README_zh-CN.md)
</div>
<br>

> LLM-powered automated county-level industry research tool: provide a county name (optional focus) and it completes the full pipeline "data collection → industry focus discovery → structuring → intelligent analysis → report generation," producing a readable Markdown industry research report. Supports three research modes: **snapshot** (current industry snapshot), **rise-fall** (industry boom-and-bust analysis), and **long-history** (century-scale county trajectory analysis).

## Key Features

- Three research modes — `snapshot`: four-dimensional current-state analysis (status/strengths/weaknesses/recommendations); `rise-fall`: county industry boom-and-bust study (origin → expansion → decline → pattern synthesis), answering 7 core questions; `long-history`: century-scale county trajectory (founding → geography → traditional economy → modern shocks → planned economy → reform era → contemporary), answering: why did this county form, what sustains it, how did it rise, why did it decline, can it be reactivated?
- Automatic industry focus discovery — Just give the county name: the system first searches for materials about the county, then the LLM identifies 3–5 candidate key industries and selects the highest-confidence focus.
- Multi-source data collection — Web search (Tavily/Serper/Bing) + whitelisted government open data with a pluggable data-source architecture; rise-fall mode issues 10 queries on modern industry booms/declines; long-history mode issues 10 long-cycle historical queries (county founding records/gazetteers/post roads and waterways/migration/state-owned factories/administrative divisions, etc.).
- LLM intelligent analysis — Prompt-engineered: snapshot outputs four-angled structured insights + executive summary; rise-fall outputs timeline/origin industry/rise factors/talent drain/model synthesis; long-history outputs historical periods/geographic logic/traditional economy/modern shocks/planned economy/reform era/contemporary view/long-cycle model synthesis.
- Automatic report generation — Standardized chapter templates, one-click Markdown output (snapshot: 6 chapters / rise-fall: 9 sections / long-history: 9 sections fixed structure).
- Data traceability — Three-layer retention: raw / processed / report. Key conclusions are bound to evidence URLs for easy review and debugging.
- Externalized configuration — YAML config + environment variables; change config without touching code.
- Abstracted interfaces — Abstract base classes at each layer; swap LLM/data sources at near-zero cost.
- Mock fallback — When API keys are missing, automatically degrades to mock data so the pipeline always runs.

## Architecture Overview

```
[User input: County] + (optional) Focus + Research Mode (--mode)
        ↓
        ├──── snapshot mode (default) ─────────────────────┐
        │                                                  ↓
        │  [search]    Multi-source collection (Web + Gov concurrent) → data/raw/
        │       ↓
        │  [discover]  Auto industry focus discovery (only if --focus not specified)
        │       ↓
        │  [storage]   Cleaning + de-dup + cache reuse                 → data/processed/
        │       ↓
        │  [llm]       4-task analysis + summary generation
        │       ↓
        │  [reporting] Chapter assembly + Markdown render              → reports/{County}_{Focus}_{Date}.md
        │
        ├──── rise-fall mode (--mode rise-fall) ────────────┐
        │                                                   ↓
        │  [search]    Modern boom-and-bust queries (10)    → data/raw/
        │       ↓
        │  [storage]   Cleaning + de-dup + cache reuse       → data/processed/
        │       ↓
        │  [rise-fall] Timeline → origin → rise → decline → talent → model → summary (7 tasks)
        │       ↓
        │  [reporting] 9-section boom-and-bust report render → reports/{County}_BoomBust_{Date}.md
        │
        └──── long-history mode (--mode long-history) ──────┐
                                                            ↓
           [search]    Long-cycle historical queries (10 for founding/gazetteer/post road/migration/SOE/admin div.) → data/raw/
                ↓
           [storage]   Cleaning + de-dup + cache reuse                              → data/processed/
                ↓
           [long-history] Periods → geography → traditional → modern → planned → reform → contemporary → model → summary (9 tasks)
                ↓
           [reporting] 9-section long-cycle trajectory report render                 → reports/{County}_LongCycle_{Date}.md
```

Three ways to use:

| Mode | Command | Use case |
|------|---------|----------|
| Specify focus | `cli -c 安吉县 -f 竹产业` | You already know the focus; dive right in (snapshot) |
| Automatic discovery | `cli -c 安吉县` | Unfamiliar with the county; let the system detect key industries (snapshot) |
| Rise-fall | `cli -c 鹤岗市 --mode rise-fall` | Study county industry boom-and-bust patterns (rise-fall) |
| Long-history | `cli -c 信丰县 --mode long-history` | Study century-scale rise/decline patterns (long-history) |

## Project Structure

```
CountyResearchAI/
├── src/county_research_ai/     # Core source code
│   ├── search/                 # Data collection layer (web_search / gov_data / collector)
│   │                           #   collector supports mode param; enables different query templates
│   ├── llm/                    # LLM analysis layer
│   │   ├── analyzer.py         #   snapshot: 4-task analysis + discover_focus
│   │   ├── rise_fall_analyzer.py # rise-fall: 7-task boom-bust analysis
│   │   ├── long_history_analyzer.py # long-history: 9-task long-cycle analysis
│   │   ├── client.py           #   OpenAI-compatible client
│   │   └── prompt_loader.py    #   Jinja2 template loader
│   ├── storage/                # Storage layer (local_fs)
│   ├── reporting/              # Report generation layer
│   │   ├── renderer.py         #   snapshot renderer
│   │   ├── rise_fall_renderer.py # rise-fall renderer (9 fixed sections)
│   │   ├── long_history_renderer.py # long-history renderer (9 fixed sections)
│   │   └── templates/          #   report / rise_fall / long_history templates
│   ├── pipeline.py             # Orchestration + mock fallback + mode routing
│   ├── cli.py                  # CLI entry (Click, --mode)
│   ├── config.py               # Config loading (YAML + .env)
│   ├── models.py               # Pydantic models (6 for rise-fall + 4 for long-history)
│   └── exceptions.py           # Exception hierarchy
├── config/                     # YAML configs
│   ├── settings.yaml           # App settings
│   └── sources.yaml            # Whitelisted government data sources
├── prompts/                    # LLM prompt templates (Jinja2)
│   ├── discovery.md            # Industry focus discovery
│   ├── industry_analysis.md    # Current-state analysis
│   ├── recommendations.md      # Recommendations
│   ├── summary.md              # Executive summary
│   ├── timeline_extraction.md  # [rise-fall] Historical timeline extraction
│   ├── origin_industry.md      # [rise-fall] Origin industry identification
│   ├── rise_analysis.md        # [rise-fall] Rise factor analysis
│   ├── decline_analysis.md     # [rise-fall] Decline factor analysis
│   ├── talent_loss.md          # [rise-fall] Talent drain analysis
│   ├── historical_pattern.md   # [rise-fall] Boom-bust model synthesis
│   ├── rise_fall_summary.md    # [rise-fall] Executive summary
│   ├── long_history_periods.md # [long-history] Historical period extraction
│   ├── geo_origin_analysis.md  # [long-history] Founding & geographic logic
│   ├── traditional_economy.md  # [long-history] Traditional era economy
│   ├── modern_shocks.md        # [long-history] Modern shocks & changes
│   ├── state_period.md         # [long-history] Planned economy re-organization
│   ├── reform_period.md        # [long-history] Reform-era industrial reshaping
│   ├── contemporary_long_view.md # [long-history] 21st-century long view
│   ├── long_history_pattern.md # [long-history] Long-cycle model synthesis
│   └── long_history_summary.md # [long-history] Executive summary
├── data/                       # Runtime artifacts (raw / processed)
├── reports/                    # Generated reports
├── tests/                      # Unit tests
├── scripts/                    # Verification scripts
└── pyproject.toml
```

## Quick Start

### 1. Environment

- Python ≥ 3.10
- Any LLM API key (DeepSeek recommended: stable and cost-effective in China)
- Any search API key (Tavily recommended: AI-optimized)

### 2. Installation

```bash
git clone https://github.com/OrdoAbChao7/CountyResearchAI.git
cd CountyResearchAI

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e ".[dev]"
```

### 3. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys (the file is gitignored and will not be committed):

```dotenv
# ---------- LLM configuration ----------
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-key        # Required
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# ---------- Search API configuration ----------
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-your-tavily-key     # Required
```

API key portals:

| Service | URL | Notes |
|---------|-----|-------|
| DeepSeek | https://platform.deepseek.com/api_keys | Stable in China, cost-effective |
| Tavily | https://app.tavily.com/dashboard/api-key | Search API optimized for AI |
| Serper | https://serper.dev | Google-based search API |
| Bing | https://www.microsoft.com/en-us/bing/apis/bing-web-search-api | Microsoft Search API |

> Mock fallback: If no API keys are configured, the pipeline automatically falls back to Mock data + Mock LLM. The full chain still runs (report content is synthetic for demonstration, not real analysis).

### 4. Run

```bash
# Set PYTHONPATH (needed if you didn't pip install -e .)
$env:PYTHONPATH="src"          # Windows PowerShell
# export PYTHONPATH=src        # macOS/Linux

# Option 1: Specify research focus (fast deep-dive, snapshot mode)
python -m county_research_ai.cli -c 安吉县 -f 竹产业

# Option 2: Auto-detect industry focus (recommended when unfamiliar with the county, snapshot mode)
python -m county_research_ai.cli -c 安吉县
# The system will first search for county materials → LLM identifies 3–5 candidate industries → selects the highest-confidence focus

# Option 3: Boom-and-bust study (rise-fall mode)
python -m county_research_ai.cli -c 鹤岗市 --mode rise-fall
# Study the county's origin → expansion → decline → patterns; outputs a 9-section boom-bust report
# Equivalent shortcut:
python -m county_research_ai.cli -c 鹤岗市 --historical

# Option 4: Century-scale trajectory analysis (long-history mode)
python -m county_research_ai.cli -c 信丰县 --mode long-history
# Study founding → geography → traditional → modern → planned → reform → contemporary; outputs a 9-section long-cycle report
# Equivalent shortcut:
python -m county_research_ai.cli -c 信丰县 --long-history

# Full options example
python -m county_research_ai.cli -c 安吉县 -f 竹产业 --no-cache --log-level INFO
```

Reports will be generated under `reports/`:
- snapshot: `{County}_{Focus}_{Date}.md`
- rise-fall: `{County}_BoomBust_{Date}.md`
- long-history: `{County}_LongCycle_{Date}.md`

### CLI Options

| Option | Short | Required | Description |
|--------|-------|----------|-------------|
| `--county` | `-c` | Yes | County name, e.g., `安吉县` |
| `--focus` | `-f` | No | Research focus, e.g., `竹产业`. If empty, auto-detect key industries (snapshot mode) |
| `--mode` | `-m` | No | Research mode: `snapshot` (default, current snapshot) / `rise-fall` (boom-bust study) / `long-history` (century-scale county trajectory) |
| `--historical` | | | Shortcut for `rise-fall` (equivalent to `--mode rise-fall`) |
| `--long-history` | | | Shortcut for `long-history` (equivalent to `--mode long-history`) |
| `--no-cache` | | | Skip cache; force re-collection and re-analysis |
| `--dry-run` | | | Validate params and print expected output only; do not run the pipeline |
| `--log-level` | | | Log level: DEBUG / INFO / WARNING / ERROR |

### rise-fall Mode Explained

The `rise-fall` mode studies a county's industry boom-bust patterns, answering 7 core questions:

1. County profile — Current stage, expansion-era industries, count of key events
2. How did it start — Foundational origin (origin industry + dominant period + mechanisms)
3. Why did it grow — 3–6 rise factors (resource endowment/policy/positioning/labor/market, etc.)
4. What drove expansion — Expansion events + industries that achieved scale
5. When were the turning points — 5–15 timeline events (origin/expansion/inflection/decline/policy/external shocks)
6. Why did it decline — 2–5 decline factors (with severity scores 0–1)
7. Which boom-bust model — Classify into one of 8 typical models (resource curse/policy-driven/market cycle/industry transfer/talent drain/path lock/diversified growth/mixed)

Report structure (9 fixed sections): Executive Summary / I. County Profile / II. Origin Industry / III. Rise Logic / IV. Expansion Mechanism / V. Key Turning Points / VI. Decline Mechanism / VII. Talent Drain Analysis / VIII. Boom-Bust Model Synthesis / IX. Conclusion

Boom-bust model types:

| Model | Description |
|-------|-------------|
| `resource_curse` | Resource-curse (resource-led rise → depletion → decline; e.g., Hegang, Yumen) |
| `policy_driven` | Policy-driven (prosperity during policy dividend → tapering → transition) |
| `market_cycle` | Market-cycle (rises and falls with macro and price cycles) |
| `industry_transfer` | Industry-transfer (inbound transfer → scaling → outbound transfer) |
| `talent_drain` | Talent-drain (decent base but persistent human-capital outflow) |
| `path_lock` | Path-lock (overreliance on a single industry; hard to pivot) |
| `diversified_growth` | Diversified co-evolution (multi-industry synergy; more resilient) |
| `mixed` | Mixed (combinations of the above) |

### long-history Mode Explained

The `long-history` mode studies century-scale county trajectories, answering core questions such as: why did this county form, what sustains it, how did it rise, why did it decline, and can it be reactivated in the future?

Research dimensions (6 consecutive historical stages):

1. Founding & geographic logic — Founding drivers, geographic structure, transport position, resources, and other deep structural factors
2. Traditional-era economy — Agricultural/handicraft/trade foundations from founding to modern era
3. Modern shocks & changes — Impacts of wars, transport revolutions, and market shocks
4. Planned economy re-organization — 1949–1978 SOEs, collectivization, administrative reshaping
5. Reform-era industrial reshaping — Post-1978 industrial transition, marketization, urbanization
6. Since 2000 — Migration, transport upgrades, industrial upgrading, marginalization or reactivation

Report structure (9 fixed sections): Executive Summary / I. Long-Cycle Overview / II. Founding & Geographic Logic / III. Traditional-Era Economy / IV. Modern Shocks & Changes / V. Planned Economy Re-organization / VI. Reform-Era Industrial Reshaping / VII. Since 2000 / VIII. Long-Cycle Model / IX. Historical Pattern Synthesis

Long-cycle model types:

| Model | Description |
|-------|-------------|
| `agricultural_hinterland` | Agricultural hinterland (long-term stability from agri endowment; limited upper bound) |
| `transport_corridor` | Transport-corridor (rises/falls with strategic routes and tech shifts) |
| `resource_frontier` | Resource frontier (resource-led rise; decline with depletion/substitution) |
| `administrative_center` | Administrative center (administrative stability shapes destiny) |
| `policy_reactivation` | Policy reactivation (state interventions reshape trajectory at key nodes) |
| `border_trade` | Border-trade hub (rises on border commerce; declines with geopolitical-economic shifts) |
| `cultural_industry` | Cultural industry (leverages historical-cultural assets) |
| `mixed` | Mixed (combinations of the above) |

### Boundaries between snapshot, rise-fall, and long-history

| Dimension | snapshot | rise-fall | long-history |
|-----------|----------|-----------|--------------|
| Focus | Current industry | Modern industry cycle | County's centuries-long fate |
| Time scale | Present | Last 30–50 years | Centuries (founding to present) |
| Core questions | Status/strengths/weaknesses/recommendations | Origin → expansion → decline → patterns | Why formed/what sustains/how it rose/why it declined/can it be reactivated |
| Search queries | General industry queries | 10 modern boom-bust queries | 10 founding/gazetteer/post road/migration/SOE/admin-division queries |
| Report sections | 6 | 9 | 9 |
| Model synthesis | None | 8 boom-bust models | 8 long-cycle models |

These three modes are independent and non-intrusive—pick based on your research goal.

### How Automatic Discovery Works

When `--focus` is not specified, the system runs:

1. Build general search queries with the county name (e.g., "安吉县 产业 发展现状"); collect from multiple sources
2. Feed search snippets to the LLM with the [prompts/discovery.md](file:///e:/CountyResearchAI/prompts/discovery.md) template
3. LLM returns JSON: 3–5 candidate industries + confidence + rationale + selected focus
4. Continue with Process → Analyze → Report using the selected focus

Fallback strategies:
- LLM call fails → return generic candidates (specialty agriculture/rural tourism/advanced manufacturing)
- No search results → fall back to "specialty agriculture"
- Parse error → default to "specialty agriculture"

## Configuration

| File | Purpose |
|------|---------|
| `.env` | Secrets (API keys), excluded from VCS |
| `config/settings.yaml` | App config (model params, timeouts, concurrency, cache TTL, etc.) |
| `config/sources.yaml` | Whitelist of government data source domains and path keywords |

### Key .env Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `deepseek` | LLM provider |
| `LLM_API_KEY` | (empty) | LLM API key; empty → MockLLM fallback |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_TEMPERATURE` | `0.3` | Generation temperature |
| `LLM_MAX_TOKENS` | `4096` | Max tokens per call |
| `SEARCH_PROVIDER` | `tavily` | Search engine |
| `TAVILY_API_KEY` | (empty) | Search API key; empty → MockSearch fallback |
| `SEARCH_MAX_RESULTS` | `10` | Results per search |
| `CACHE_TTL_HOURS` | `24` | Cache TTL (hours) |
| `LOG_LEVEL` | `INFO` | Log level |

## Testing

```bash
# Run all unit tests (external APIs mocked; real keys not required)
$env:PYTHONPATH="src"
python -m pytest --no-cov -q

# View coverage details
python -m pytest --cov=county_research_ai --cov-report=term-missing --cov-report=html:htmlcov
```

HTML coverage report is generated at `htmlcov/index.html`.

## Runtime Artifacts

```
data/raw/{County}/{Date}/raw_docs.json      # Raw collected documents
data/processed/{County}/{Focus}.json        # Cleaned and structured data
reports/{County}_{Focus}_{Date}.md           # snapshot report
reports/{County}_BoomBust_{Date}.md          # rise-fall report
reports/{County}_LongCycle_{Date}.md         # long-history report
```

## Tech Stack

| Category | Choice |
|----------|--------|
| Language | Python 3.10+ |
| LLM client | openai SDK (compatible with DeepSeek / Qwen / OpenAI) |
| Data validation | Pydantic v2 |
| CLI | Click |
| HTTP | httpx |
| Templating | Jinja2 |
| Retries | tenacity |
| HTML parsing | beautifulsoup4 |
| Testing | pytest + pytest-cov |

## MVP Scope

Current version (v0.3) intentionally keeps scope tight:

- Single-county, single-run research (no multi-county comparisons yet)
- Markdown output only (no PDF/HTML export yet)
- Local filesystem storage (no DB yet)
- CLI interaction (no Web UI yet)
- Single-threaded pipeline (no multi-agent yet)

> v0.3 adds the `long-history` mode: century-scale county trajectory analysis (founding → geography → traditional → modern → planned economy → reform era → contemporary → long-cycle model synthesis), coexisting with `rise-fall` from v0.2 and `snapshot` from v0.1.

## License

MIT
