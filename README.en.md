# CountyResearchAI

> An LLM-assisted workflow for county-level industry research: collect evidence, identify an industry focus, analyze structured inputs, and render a traceable Markdown report.

[中文文档](README.md)

CountyResearchAI accepts a county name and an optional research focus, then orchestrates data collection, industry-direction discovery, structured processing, LLM-assisted analysis, and report rendering. It supports three complementary modes:

- **`snapshot`** — a current industry landscape: situation, strengths, weaknesses, and recommendations.
- **`rise-fall`** — a modern industrial rise-and-decline study.
- **`long-history`** — a long-cycle county development history from formation and geography through contemporary change.

> **Research note:** Generated output is research assistance, not investment, legal, policy, or professional advice. Verify cited sources and claims before making decisions.

## Key capabilities

| Capability | Description |
|---|---|
| Three research modes | Use a current-state snapshot, a modern industrial-cycle study, or a long-horizon historical analysis. |
| Focus discovery | If no focus is supplied, the system searches for county information and asks an LLM to select the highest-confidence direction from several candidates. |
| Multi-source collection | Supports web search providers and a government-data allowlist through an extensible source layer. |
| LLM-assisted analysis | Uses prompt templates to create structured insights, timelines, factors, models, and executive summaries. |
| Markdown reports | Produces standardized report structures: 6 chapters for `snapshot`, 9 sections for `rise-fall`, and 9 sections for `long-history`. |
| Evidence retention | Retains raw, processed, and report layers; key conclusions can reference evidence URLs. |
| Configurable integrations | Uses YAML and environment variables so providers can be changed without modifying business logic. |
| Graceful mock mode | Runs end-to-end with mock search and mock LLM behavior when API keys are not configured. |

## Architecture

```text
County name + optional focus + --mode
        ↓
┌──────────────────────── snapshot ────────────────────────┐
│ search → optional focus discovery → storage / cache       │
│       → structured LLM analysis → Markdown report         │
└──────────────────────────────────────────────────────────┘
        ↓
┌────────────────────── rise-fall ─────────────────────────┐
│ modern-history queries → timeline / origin / rise /       │
│ decline / talent / model analysis → 9-section report      │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────── long-history ────────────────────────┐
│ county formation / geography / historical-economy queries │
│ → historical-stage analysis → long-cycle report           │
└──────────────────────────────────────────────────────────┘
```

The source tree separates collection, analysis, storage, reporting, configuration, prompt templates, data, reports, and tests. This keeps external data providers and LLM providers replaceable.

## Research modes

| Mode | Typical command | Question it answers | Time horizon |
|---|---|---|---|
| `snapshot` | `cli -c AnjiCounty -f BambooIndustry` | What is the current situation, opportunity, constraint, and recommendation set? | Present |
| `snapshot` with discovery | `cli -c AnjiCounty` | Which industry direction should be investigated first? | Present |
| `rise-fall` | `cli -c Hegang --mode rise-fall` | How did an industry emerge, expand, decline, and what pattern explains the cycle? | Approximately 30–50 years |
| `long-history` | `cli -c Xinfeng --mode long-history` | Why did the county form, how did geography and institutions shape it, and can it be reactivated? | Centuries to the present |

### `rise-fall` mode

This mode extracts a timeline, originating industry, rise factors, decline factors, talent-outflow signals, and an industrial-cycle model. The rendered report has nine fixed sections: executive summary, county profile, founding industry, rise logic, expansion mechanism, inflection points, decline mechanisms, talent analysis, and a synthesized rise-and-fall model.

### `long-history` mode

This mode examines six connected historical stages: county formation and geography, traditional economic life, modern shocks, planned-economy reorganization, reform-era industrial reshaping, and recent development change. It renders an executive summary plus eight long-cycle analytical sections.

## Requirements

| Requirement | Notes |
|---|---|
| Python | Python 3.10 or later. |
| LLM provider | Any configured OpenAI-compatible provider; DeepSeek is a documented example. |
| Search provider | Any configured search provider; Tavily is a documented example. |
| API keys | Optional for smoke testing because the pipeline has a mock fallback. Required for factual live research. |

## Installation

```bash
git clone https://github.com/OrdoAbChao7/CountyResearchAI.git
cd CountyResearchAI

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -e ".[dev]"
```

## Configure providers

Create a local environment file:

```bash
cp .env.example .env
```

Then configure compatible providers. The following names are examples; never commit real keys.

```dotenv
LLM_PROVIDER=deepseek
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your-search-api-key
```

`.env` is excluded from version control. If no keys are configured, the system falls back to mock data and a mock LLM so the pipeline can be exercised; mock reports are illustrative only and must not be treated as factual analysis.

## Run the CLI

Set `PYTHONPATH` when the package has not been installed in editable mode:

```powershell
$env:PYTHONPATH="src"
```

### Specify a known industry focus

```bash
python -m county_research_ai.cli -c 安吉县 -f 竹产业
```

### Discover a focus automatically

```bash
python -m county_research_ai.cli -c 安吉县
```

The system collects a general information set, asks the LLM to identify 3–5 candidate industries, chooses the highest-confidence focus, and then continues with the snapshot workflow.

### Study industrial rise and decline

```bash
python -m county_research_ai.cli -c 鹤岗市 --mode rise-fall
# Equivalent shortcut:
python -m county_research_ai.cli -c 鹤岗市 --historical
```

### Study long-cycle development history

```bash
python -m county_research_ai.cli -c 信丰县 --mode long-history
# Equivalent shortcut:
python -m county_research_ai.cli -c 信丰县 --long-history
```

### Useful options

| Option | Short form | Meaning |
|---|---|---|
| `--county` | `-c` | Required county name. |
| `--focus` | `-f` | Optional industry focus; omit it to enable focus discovery in snapshot mode. |
| `--mode` | `-m` | `snapshot` (default), `rise-fall`, or `long-history`. |
| `--historical` | — | Shortcut for `--mode rise-fall`. |
| `--long-history` | — | Shortcut for `--mode long-history`. |
| `--no-cache` | — | Bypass the local collection / analysis cache. |
| `--dry-run` | — | Validate parameters and show expected output without executing the pipeline. |
| `--log-level` | — | Set `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

Reports are written to `reports/`. Raw collection results and processed artifacts are retained beneath `data/raw/` and `data/processed/` to support review and debugging.

## Configuration

| File | Purpose |
|---|---|
| `.env` | Sensitive provider configuration; never commit this file. |
| `config/settings.yaml` | Application settings such as model parameters, timeouts, concurrency, cache TTL, and log level. |
| `config/sources.yaml` | Government-data domain allowlist and source-path keywords. |
| `prompts/` | Jinja2 templates for discovery, analysis, recommendations, summaries, and historical research tasks. |

## Testing

The unit-test suite uses mock external APIs, so a real provider key is not required for tests.

```powershell
$env:PYTHONPATH="src"
python -m pytest --no-cov -q

# Optional coverage report
python -m pytest --cov=county_research_ai --cov-report=term-missing --cov-report=html:htmlcov
```

The HTML coverage report is written to `htmlcov/index.html`.

## Project boundaries

The current version deliberately limits scope to a single county per run, Markdown output, local file-system storage, CLI interaction, and a sequential pipeline. It does not yet provide a database, web UI, multi-county comparison, automatic PDF/HTML report export, or multi-agent execution.

Generated research should be treated as a starting point for investigation. Check source URLs, data dates, model limitations, and domain-specific assumptions before using a report in an investment, policy, legal, or operational decision.

## Repository structure

```text
CountyResearchAI/
├── src/county_research_ai/     # Search, LLM, storage, reporting, pipeline, CLI
├── config/                     # YAML settings and source allowlist
├── prompts/                    # Jinja2 prompt templates
├── data/                       # Raw and processed artifacts
├── reports/                    # Generated Markdown reports
├── tests/                      # Unit tests
├── scripts/                    # Validation scripts
└── pyproject.toml
```

## License

MIT License.
