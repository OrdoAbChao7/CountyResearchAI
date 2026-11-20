# Live Smoke Record — 2026-11-20

Status: runs 1–3 and 5 `PASS_ENGINEERING`; run 4 `FAILED`; run 5
`NO_PROGRESS` (`no_supported_claims`); adaptive path completed, empty branch
offline-only

This records **five** explicitly authorized Live runs: the initial smoke, one
corrected follow-up (“再跑一次”), one region-gate verification (“跑第三次”),
one 2024-window / adaptive-retrieval verification (“跑第四次 Live”), and one
verification of the repaired adaptive follow-up path (“跑第五次”). Runs 1–3 and
5 completed; run 4 failed in the adaptive follow-up collection before
verification. They prove that the real FastAPI job path, DeepSeek client,
Tavily provider, event stream, region gate, evidence graph and report
projections work together (runs 1–3 and 5) and that the repaired follow-up path
can finish with real providers (run 5). They are **not** a Live evaluation, do
not replace MOCK tests, and do not satisfy M5.

- Cost gate: [LIVE_SMOKE_COST_GATE.md](LIVE_SMOKE_COST_GATE.md)
- Script: `scripts/run_live_smoke.py`
- Artifacts: `experiments/quality/live_smoke_20261120/`,
  `experiments/quality/live_smoke_20261120_second/`,
  `experiments/quality/live_smoke_20261120_third/`,
  `experiments/quality/live_smoke_20261120_fourth/`,
  `experiments/quality/live_smoke_20261120_fifth/`
- First job: `d367c9b277cf47d086d28f9824d661e5`
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

Regression: `tests/test_region_relevance.py` (13 tests) covers the replay,
county mention beating a national source marker, prefecture-only context,
unknown documents being kept, the short-name boundary rule, and the three
collector entry points. The backend suite is `795 passed`; the Anji MOCK demo
is unchanged (25 nodes / 33 edges, 1 SUPPORTED / 5 NOT_COMPARABLE, 2 conflicts,
3 gaps).

This section is the offline verification that preceded the third run. The third
run then exercised the gate with a live provider and exposed a short-name false
positive, described below. The period blocker is untouched: the kept 安吉
sources are from 2011/2023/2025, so a 2024 contract still accepts zero claims.

## Third run (region-gate verification, 2026-11-20)

The user then said “跑第三次”, authorizing one bounded smoke to verify the gate
with a real provider. Command:

```bash
LIVE_SMOKE_RUN_ROOT=experiments/quality/live_smoke_20261120_third \
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

| Item | Third run |
| --- | --- |
| Job | `007487e8e7494e3fba1770c1f7b0781f` |
| Status / mode | `SUCCEEDED` / `LIVE` |
| Outcome | `NO_PROGRESS` (`no_supported_claims`) |
| Focus | `竹产业` |
| LLM / tokens | 2 / 4,693 (discovery completion 1,224) |
| Searches | 7 |
| Graph | 165 nodes / 1,077 edges (800 returned) |
| Report | 0 verified / 133 `NOT_COMPARABLE`; 6 conflicts; 2 gaps |
| Sources | 8 |
| Guard | 0 violations; 29.23 s |
| Estimated cost | model $0.001256; ≤ $0.0585 total |

What the gate did:

- The persisted set is Anji-centred. The national statistical bulletins, the
  Fujian bulletin and the Luoyang plan seen in the second run are gone. The
  remaining government pages (NDRC, forestry) are articles about Anji and
  contain multiple `安吉县` mentions.
- One false positive slipped through: the Guizhou five-year plan contains
  “安吉精铸” and “正安吉他” (a company/project name and a guitar brand), so the
  short-name substring rule classified it `REGION`. Its content has zero
  occurrences of the full `安吉县`.
- The classifier was fixed: the full administrative name is required inside
  document content, and the short name is matched only in title/snippet/URL and
  only on a word boundary. Replaying this run's stored source content marks the
  Guizhou plan `OTHER_REGION` (7 region / 1 other-region). No provider calls
  were made for that replay.
- No `retrieval.round.*` event appears: the adaptive loop stopped before any
  follow-up round, so `collect_adaptive` fetched no additional documents. The
  gate ran inside `SearchCollector.collect`. The `retrieval.region_filtered`
  event was added after this run, so its collect-time drop count is not in the
  artifact.

The run still accepted zero claims: all 133 structured claims are outside the
2024 window (sources from 2011/2023/2025/2026). Region filtering removed
sources, not the period gap.

## Fourth run (adaptive follow-up failure, 2026-11-20)

The user then said “跑第四次 Live”, authorizing one further bounded smoke to
exercise the 2024-window and adaptive-retrieval fixes with a real provider.
Command:

```bash
LIVE_SMOKE_RUN_ROOT=experiments/quality/live_smoke_20261120_fourth \
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

| Item | Fourth run |
| --- | --- |
| Job | `4f4d6610f48248a599e6b112ce5b9ee0` |
| Status / mode | `FAILED` / `LIVE` |
| Outcome | `FAILED` (`execution_error`) |
| Focus | `竹产业` |
| LLM / tokens | 2 / 4,651 (preflight 13; discovery completion 1,204) |
| Searches | 11 Tavily calls (7 initial + 4 follow-up) |
| Events | 14, ending in `job.failed` |
| Graph | HTTP 409 (job not completed) |
| Report | HTTP 200 but empty: 0 verified / 0 unverified; no sources persisted |
| Guard | 0 violations; 39.64 s guard, 31.85 s job elapsed |
| Estimated cost | model $0.001241; Tavily $0.088; ≤ $0.0905 |
| Verdict | `FAIL` (`FAILED` terminal state) |

What ran before the failure:

- The region gate ran live in `stage.collect`. It assessed 31 provider-returned
  documents: 27 kept, 4 dropped (`other_region` 3, `national` 1). Eight
  documents were returned after ranking and dedup.
- `stage.discover.completed` reported `竹产业`; the discovery completion did not
  hit the 2,048-token cap.
- The first `retrieval.period_coverage` event reported `target_years=["2024"]`,
  22 selected claims, 1 in-window claim, 1 in-window source,
  `period_coverage_met=true`, `topic_coverage_met=false`, and four missing
  slots (`snapshot:economic_scale`, `snapshot:industry_structure`,
  `snapshot:policy`, `snapshot:risk`). This is the first live evidence that the
  Phase 2/3 window and period-coverage plumbing is active.
- The adaptive controller started round 2 with four queries and recorded their
  real text:
  - `安吉县 2024年 统计公报 国民经济 竹产业 产值 产量 面积 最新`
  - `安吉县 2024年 竹产业 安吉县竹产业产业结构与县域贡献`
  - `安吉县 竹产业 政策文件 十四五 专项扶持 实施意见`
  - `安吉县 2024年 竹产业 安吉县竹产业现状风险与发展瓶颈`
  All four were routed to the `gov` channel because the generated gap queries
  map to `ECONOMIC_SCALE`/`POLICY_PLANNING`.

The failure:

- `collect_adaptive` sent all four queries through `GovDataProvider`. The guard
  recorded four successful Tavily calls, each returning six documents, so the
  upstream search did not fail.
- `GovDataProvider` keeps only documents on its government whitelist and
  returned an empty list for all four queries.
- `SearchCollector._run_tasks` treats an empty aggregate result as “all search
  tasks failed” when `pipeline.fail_fast=True` and raises `SearchError`; the
  worker records `job.failed` with `ResearchStageError`.
- This conflates a legitimate zero-result gap query with a provider failure.
  The fail-fast branch is pre-existing (`4400668`, 2026-08-05, `git blame` on
  `collector.py:355`). This is the first live run to enter the adaptive
  follow-up path; the third run stopped before any follow-up round.
- Offline reproduction without any provider call: a stub `gov` provider that
  returns `[]` for one gov-channel `GeneratedQuery` raises the same
  `SearchError("所有搜索任务均失败", context={"tasks_count": 1,
  "providers": ["gov"]})`. No code was changed for this run.

Consequences:

- The job did not reach verification, evidence persistence, graph projection or
  a final report; the empty report and HTTP 409 graph are consistent with the
  `FAILED` state, not evidence that no sources existed.
- The single in-window claim is only a coverage count. It was not verified and
  is not a 2024 research result.
- No second paid attempt was made after the failure. A fifth run was later
  authorized by “跑第五次”; it completed and is recorded below.

### Follow-up fix (offline, 2026-11-20)

The defect was fixed without a provider call. `SearchCollector._run_tasks` now
tracks failed tasks separately from successful empty results and raises
`SearchError` only when every task raised. An empty adaptive follow-up returns
an empty `AdaptiveCollectionResult`; the coordinator stops that round with
`ZERO_MARGINAL_EVIDENCE` and lets the job finish with the evidence it has.

Regressions in `tests/test_search_collector.py`:

- `test_empty_gov_followup_is_not_a_search_failure` — a gov query returning
  `[]` yields an empty result, not `SearchError`;
- `test_all_provider_errors_still_fail_fast` — all providers raising still
  raises, with `failed_tasks == tasks_count`;
- `test_mixed_empty_and_error_does_not_fail_fast` — one empty success plus one
  provider error is not an all-task failure.

`pytest --no-cov -q` → `830 passed`; `ruff check src tests` → clean. The fifth
run was later authorized and exercised this repaired path with a real provider;
because both follow-up rounds returned documents, it did not exercise the empty
branch itself. See the fifth-run section below.

## Fifth run (adaptive follow-up verification, 2026-11-20)

The user then said “跑第五次”, authorizing one further bounded smoke to verify
the repaired adaptive follow-up path with a real provider. Command:

```bash
LIVE_SMOKE_RUN_ROOT=experiments/quality/live_smoke_20261120_fifth \
LLM_PROVIDER=deepseek \
LLM_BASE_URL=https://api.deepseek.com/v1 \
LLM_MODEL=deepseek-flash \
SEARCH_PROVIDER=tavily \
PYTHONPATH=src python scripts/run_live_smoke.py \
  --env-file E:/Projects/CountyResearchAI/.env --confirm-paid
```

| Item | Fifth run |
| --- | --- |
| Job | `27a8fdb796f94b689ff4fbba78b2d798` |
| Status / mode | `SUCCEEDED` / `LIVE` |
| Outcome | `NO_PROGRESS` (`no_supported_claims`) |
| Focus | `竹产业` |
| LLM / tokens | 2 / 4,948 (preflight 13; discovery completion 1,398 < 2,048) |
| Searches | 15 Tavily basic (7 initial + 4 round 2 + 4 round 3) |
| Events | 35, ending in `job.completed` |
| Graph | 45 nodes / 139 edges, not truncated |
| Report | 6 sections, 22 citations, 10,578 characters |
| Verification | 0 verified / 22 unverified: 21 `NOT_COMPARABLE`, 1 `INSUFFICIENT` |
| Conflicts / gaps | 4 / 2 |
| Sources | 10; persisted verdicts 9 `region` / 1 `unknown` |
| Region gate | 24 kept / 7 dropped (6 `other_region`, 1 `national`) |
| Adaptive stop | `max_rounds_reached`; `total_turns=2` |
| Guard | 0 violations; job 57.476 s; guard 66.69 s |
| Estimated cost | model $0.001373; Tavily $0.12; ≤ $0.1227 |

What the repaired path did:

- The initial `retrieval.period_coverage` reported target `2024`, 21 selected
  claims, 0 in-window claims/sources, `period_gap=true`, and five missing slots.
- Round 2 generated four target-year queries:
  `安吉县 2024年 统计年鉴 统计公报 主要经济指标`,
  `安吉县 竹产业 2024年 产值 产量 统计数据`,
  `安吉县 2024年 统计公报 国民经济 竹产业 产值 产量 面积 最新`, and
  `安吉县 2024年 竹产业 安吉县竹产业产业结构与县域贡献`.
  It fetched 12 documents and kept 3; coverage stayed at 22 selected, 0
  in-window.
- Round 3 sent the same four queries, fetched 24 documents (cumulative) and
  kept 3; the controller then stopped with `max_rounds_reached`. The repeated
  query set produced no new in-window claim; this is an efficiency observation,
  not a failure, and all 15 searches remained within the 24-search cap.
- The job continued through `evidence.ingested` (14 documents / 119 items / 17
  region-excluded), question-tree coverage 4/6, gaps `q_policy`/`q_risks`,
  conflicts, synthesis, evidence persistence, graph projection and report
  rendering. This is the repaired path completing instead of raising
  `SearchError`.

What the run found:

- The verifier accepted no claim. The 22 report findings are 21
  `NOT_COMPARABLE` (17 outside the requested window with period `2025`, four
  with a missing period) plus one `INSUFFICIENT` claim from 2007 with an unknown
  region.
- No persisted claim has a 2024 period. Of 136 claims, 110 are `2025`, 16 have
  no period, four are `2023`, three are `2022`, and one each is
  `2018`/`2007`/`2005`. The supplemental rounds changed the source mix but did
  not produce a 2024 claim. The 2024 statistical bulletin was not present in
  this result set; no 2024 data was fabricated.
- The specific empty-follow-up branch was **not** exercised: both supplemental
  rounds returned three documents. The three offline regressions remain the
  direct evidence for that fix.
- A separate claim-region false positive is visible in the evidence store: 10
  claims have `region_id=年全县` and one has `占全县`, all with
  `region_source=claim`. Statements such as `2023年全县竹产业总产值达到180.28亿元`
  are tokenised as `年全县` by the place-name regex
  (`search/region_relevance.py:48`); `classify_claim_region` checks the full
  `安吉县` in claim text and then treats that token as another region
  (`evidence/claim_region.py:153`, `:174`). The 22 report findings are not among
  these 11 claims, and none of the 11 carries a 2024 period, so this is not the
  explanation for the 2024 gap. It is an unresolved claim-attribution defect:
  it wrongly excludes county-level claims and needs a separate fix and
  regression before another quality conclusion.

Verdict: engineering `PASS_ENGINEERING`; research `NO_PROGRESS`; real 2024
coverage is still **not demonstrated**. The run proves that the repaired
adaptive path completes with non-empty follow-ups, not that the empty branch is
live-correct, and not that the live 2024 retrieval problem is solved.

## What this does and does not prove

Proved:

- DeepSeek `deepseek-flash` authentication, chat completion and token usage;
- Tavily basic search with the existing provider adapter;
- real job execution through the existing SQLite `JobStore`/`JobRunner`;
- fine-grained events, evidence persistence, graph projection and report
  projection on live data (runs 1–3 and 5; run 4 failed before persistence);
- an explicit contract focus is preserved through discovery after the fix;
- the region gate runs live: the third run kept its persisted set Anji-centred,
  the fourth run dropped 3 other-region plus 1 national result before ingestion,
  and the fifth run kept 24 / dropped 7 (6 other-region, 1 national) with 9
  `region` / 1 `unknown` persisted source verdicts;
- the fourth run recorded a 2024 `retrieval.period_coverage` event (1 in-window
  claim/source) and four target-year follow-up query texts, so the Phase 2/3
  window and coverage plumbing is active with a real provider;
- the fifth run completed the repaired adaptive path with two non-empty
  follow-up rounds and reached evidence persistence, graph and report instead of
  failing in `collect_adaptive`;
- the fifth run recorded a 2024 target window, real target-year query text and
  `in_window_claim_count=0` in both rounds, so the absence of a 2024 result is
  visible rather than silently promoted;
- the retry/call caps and cost gate were respected in all five runs (no
  violations).

Not proved:

- Live research quality or supported-claim coverage;
- that the fixed short-name rule behaves correctly under a fresh live provider
  response; the fifth run's source set did not exercise the Guizhou-plan
  collision, so the third-run false positive still has only offline replay
  evidence;
- that the 2024 fixes produce a verified 2024 claim; the fifth run completed but
  had zero in-window claims and zero verified facts;
- that the fixed empty-follow-up branch completes a full paid run; the fifth
  run's follow-up rounds both returned documents, so that branch has only
  offline regressions;
- that claim-level region attribution is correct in production; the fifth run
  exposed 10 `年全县` and one `占全县` false positives (see above);
- a Live evaluation, semantic Judge, 40–60 sealed tasks, or human adjudication;
- that a sixth run is authorized.

## Next actions (not executed)

1. Fix the root `.env` provider/model mismatch, or make the override explicit in
   a local launch profile.
2. The adaptive empty-result handling is fixed offline. The fifth run verified
   the repaired path with non-empty follow-ups; a future Live run whose
   follow-up is genuinely all-empty would be needed to exercise the empty branch
   itself. Do not run it without a new authorization.
3. Fix the claim-region false positive: `年全县` / `占全县` tokens must not be
   treated as other regions, and a boundary-safe short county name in claim text
   must be considered. Add regressions using `2023年全县...` and
   `2022年全县...` claims; do not loosen the verifier or the document gate.
4. Region relevance: the deterministic gate ran live in the fourth and fifth
   runs, but the specific short-name false positive from the third run still has
   only offline replay evidence. Re-check it in a future completed run that
   retrieves the Guizhou plan.
5. Inspect the `2024 → outside_requested_window:2026` claim against its source
   span and add a regression if the period parser is wrong.
6. Investigate the 2024 retrieval gap: the fifth run found a 2025 bulletin and
   older material but no 2024 period, so the query/source set, not only the
   verifier, needs review. Decide whether the smoke contract should use a wider
   window or a 2024-specific source set; do not relax the period guard.
7. Ask for a fresh authorization before a sixth paid run; then repeat the
   bounded smoke and compare.
