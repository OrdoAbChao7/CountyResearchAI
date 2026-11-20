# Live Smoke Record — 2026-11-20

Status: `PASS_ENGINEERING` / `NO_SUPPORTED_CLAIMS`

This records **two** explicitly authorized Live runs: the initial smoke and one
corrected follow-up (“再跑一次”) with a 2,048-token discovery allowance and the
explicit-focus fix. They prove that the real FastAPI job path, DeepSeek client,
Tavily provider, event stream, evidence graph and report projections work
together. They are **not** a Live evaluation, do not replace MOCK tests, and do
not satisfy M5.

- Cost gate: [LIVE_SMOKE_COST_GATE.md](LIVE_SMOKE_COST_GATE.md)
- Script: `scripts/run_live_smoke.py`
- Artifacts: `experiments/quality/live_smoke_20261120/`
- Job: `d367c9b277cf47d086d28f9824d661e5`
- Command:

```bash
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

## Provider configuration finding

The root `.env` currently says:

```text
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.1-flash-lite
```

but the configured `LLM_API_KEY` is a DeepSeek key: a free `GET
https://api.deepseek.com/models` returned HTTP 200 and listed `deepseek-flash`
and `deepseek-v4-pro`, while the same key against the Gemini endpoint returned
HTTP 400 `Please pass a valid API key`.

The smoke therefore used process-level overrides and did **not** change the
root `.env` or the main workspace:

```text
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-flash
SEARCH_PROVIDER=tavily
```

The `.env` mismatch should be fixed deliberately by the owner; otherwise the
normal API path (without the smoke overrides) will fail authentication.

## Observed result

| Item | Observed |
| --- | --- |
| Job status | `SUCCEEDED` |
| Mode label | `LIVE` |
| Outcome | `NO_PROGRESS` / `no_supported_claims` |
| Job elapsed | 30.6 s |
| Events | 28, including question tree, agents, synthesis, report |
| LLM calls | 2 (1 preflight, 1 discovery) |
| Prompt / completion tokens | 2,848 / 771 |
| Tavily basic searches | 7 (6 results each) |
| Sources persisted | 8 |
| Graph | 273 nodes / 1,869 edges, returned 273 nodes / 800 edges, truncated |
| Report sections | summary, verified-facts, disputes, gaps, sources, method |
| Verified / unverified claims | 0 / 239 `NOT_COMPARABLE` |
| Conflicts / gaps | 7 / 2 |
| Guard violations | 0 |
| Estimated cost | $0.00089 model; $0.056 if Tavily credits are paid; ≤ $0.0578 total |

The job succeeded, so the existing `JobRunner` terminal-state semantics were
not altered by the live data. The report was generated programmatically, the
graph projection returned, and the SSE event log was persisted.

## What the live run exposed

1. **Discovery focus fell back.** The contract asked for `竹产业`, but the
   persisted question tree and `stage.discover.completed` say `特色农业`. The
   discovery LLM call produced exactly 768 completion tokens (the smoke cap),
   so the JSON was likely truncated and the parser returned no selected focus;
   the handler then used its default. The cap was a smoke budget choice, not a
   production setting. A future run needs a larger discovery allowance.
2. **Retrieval relevance is poor.** Persisted sources include national
   statistics, Fujian statistics, Luoyang planning and a Hunan Lanshan bamboo
   plan. The source list is not region-locked to Anji. The query generator plus
   Tavily basic search did not keep the result set on-topic.
3. **The verifier rejected every claim.** All 239 structured claims are
   `NOT_COMPARABLE`, mostly because their period is outside the requested 2024
   window (2022, 2023, 2025, 2026); a few have no usable period. This is the
   time-window guard working, but it means the live run produced no verified
   fact.
4. **One period attribution looks suspicious.** The report lists
   “2024 年竹产业产值为 6.855 亿元” as `outside_requested_window:2026`. The
   claim text says 2024 but the verifier attributed 2026, probably from the
   source publication date. This needs a focused period-extraction test before
   the next Live run; do not call it a false rejection until the source span is
   inspected.
5. **Graph scale is real.** A single live query set produced 273 graph nodes
   and 1,869 edges, which is already above the 400/800 display budget after
   edge truncation. The synthetic 400-node browser test remains a valid
   performance fixture, not a substitute for a real-investigation benchmark.

## Second run (corrected, 2026-11-20)

The user then said “再跑一次”. Before the second paid call:

- `ResearchApplication.discover_focus` was fixed so an explicit contract focus
  wins over the discovery result (`src/county_research_ai/application/research.py`);
- a regression test `test_explicit_focus_wins_over_discovery` was added and
  passes;
- the smoke output allowance was raised from 768 to 2,048 tokens;
- a second $0.25 cap and stop conditions were recorded in the cost gate.

| Item | First run | Second run |
| --- | --- | --- |
| Job | `d367c9b2…` | `fdf7f3e86d444419967124236c4cc1ad` |
| Status / mode | `SUCCEEDED` / `LIVE` | `SUCCEEDED` / `LIVE` |
| Outcome | `NO_PROGRESS` | `NO_PROGRESS` |
| Discovered focus | `特色农业` (cap hit) | `竹产业` (explicit focus preserved) |
| Discovery completion | 768 (cap) | 838 (under 2,048 cap) |
| LLM / tokens | 2 / 3,619 | 2 / 3,944 |
| Searches | 7 | 7 |
| Graph | 273 nodes / 1,869 edges | 256 nodes / 1,785 edges |
| Report | 0 verified / 239 `NOT_COMPARABLE` | 0 verified / 224 `NOT_COMPARABLE` |
| Conflicts / gaps | 7 / 2 | 7 / 2 |
| Sources | 8 | 8 |
| Estimated cost | ≤ $0.0578 | ≤ $0.0579 |

The second run confirms the focus fix: `stage.discover.completed` and the
question tree both say `竹产业`, and the report is now a bamboo-industry report.
It still accepted zero claims. The 2024 window rejected the available
2023/2025/2026 material (and one 2011 source), and retrieval still included
Fujian, Luoyang and national-statistics pages. Focus selection was not the
remaining blocker; region-locked retrieval and period coverage are.

Artifacts: `experiments/quality/live_smoke_20261120_second/`.

Command:

```bash
LIVE_SMOKE_RUN_ROOT=experiments/quality/live_smoke_20261120_second \
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

## Region retrieval fix (offline replay, 2026-11-20)

After the second run, the retrieval layer was given a deterministic region gate
(`src/county_research_ai/search/region_relevance.py`). Each result is classified
before ranking and evidence ingestion:

- `REGION` — names the target county (or its distinctive short name);
- `CONTEXT` — names only the target province/prefecture, never the county;
- `OTHER_REGION` — names a different province/city/county;
- `NATIONAL` — a national statistical/government source, or a title announcing
  national coverage, without the county;
- `UNKNOWN` — no identifiable region.

Only `REGION` and `UNKNOWN` are evidence-bearing. The gate runs in
`SearchCollector.collect`, `collect_supplemental` and `collect_adaptive` (the
deep-research path); `collect_adaptive` reports `region_filtered_documents` in
its usage payload, which flows into `retrieval.round.completed`.

Replaying the eight source titles/URLs persisted by the second run:

| Recorded source | Verdict |
| --- | --- |
| (湖州市)2025年安吉县国民经济和社会发展统计公报 | `REGION` (kept) |
| 小蜂观察：浙江省安吉县竹产业高质量发展路径分析 | `REGION` (kept) |
| 浙江省安吉县竹产业2011年预计产值可达130多亿 | `REGION` (kept) |
| 中华人民共和国2023年国民经济和社会发展统计公报 | `NATIONAL` (dropped) |
| 2026年8月份规模以上工业增加值增长5.2% | `NATIONAL` (dropped) |
| 国家统计局信息公开 | `NATIONAL` (dropped) |
| 统计公报_数据发布_福建省人民政府门户网站 | `OTHER_REGION` (dropped) |
| 洛阳市…第十五个五年规划纲要 | `OTHER_REGION` (dropped) |

Regression: `tests/test_region_relevance.py` (10 tests) covers the replay,
county mention beating a national source marker, prefecture-only context,
unknown documents being kept, and the three collector entry points. The backend
suite is `792 passed`; the Anji MOCK demo is unchanged (25 nodes / 33 edges,
1 SUPPORTED / 5 NOT_COMPARABLE, 2 conflicts, 3 gaps).

This is an offline verification against already-recorded sources. It does not
prove the live behaviour of the search providers, and no third paid run was
made. The period blocker is untouched: the three kept 安吉 sources are from
2011/2023/2025, so a 2024 contract would still accept zero claims.

## What this does and does not prove

Proved:

- DeepSeek `deepseek-flash` authentication, chat completion and token usage;
- Tavily basic search with the existing provider adapter;
- real job execution through the existing SQLite `JobStore`/`JobRunner`;
- fine-grained events, evidence persistence, graph projection and report
  projection on live data;
- an explicit contract focus is preserved through discovery after the fix;
- the retry/call caps and cost gate were respected (no violations).

Not proved:

- Live research quality or supported-claim coverage;
- regional relevance of the retrieval layer;
- a Live evaluation, semantic Judge, 40–60 sealed tasks, or human adjudication;
- that a third run is authorized.

## Next actions (not executed)

1. Fix the root `.env` provider/model mismatch, or make the override explicit in
   a local launch profile.
2. Region relevance: the deterministic gate described above is in place and
   verified offline against the recorded sources; re-check it with a fresh
   authorization before the next paid run.
3. Inspect the `2024 → outside_requested_window:2026` claim against its source
   span and add a regression if the period parser is wrong.
4. Decide whether the smoke contract should use a wider date window or a
   2024-specific source set; the current 2024 window rejects most available
   live material.
5. Ask for a fresh authorization before a third paid run; then repeat the
   bounded smoke and compare.
