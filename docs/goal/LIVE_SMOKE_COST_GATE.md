# Live Smoke Cost Gate — 2026-11-20

Status: `THREE_SMOKES_AUTHORIZED_2026-11-20`

## Authorization

The user explicitly authorized paid provider calls and asked for one Live run:

- 2026-11-20: “需要api我可以提供ds 的api在根目录的.env文件夹下面，允许付费调用”
- 2026-11-20: “跑一次 Live”

This authorization covers **one** bounded smoke run only. It does not authorize a
Live evaluation campaign, a semantic Judge, a 40–60 task benchmark, retries
beyond the limits below, or any deployment/push.

The user then asked “再跑一次” after the first smoke exposed a truncated
discovery response and a fallback focus. That authorizes **one additional**
bounded smoke with a 2,048-token discovery allowance and an explicit
`竹产业` focus. It does not authorize any further runs.

After the region-relevance gate was implemented and replayed offline against the
second run's recorded sources, the user said “跑第三次”. That authorizes
**exactly one more** bounded smoke to verify the gate with a real provider. It
does not authorize a Live evaluation, a semantic Judge, a 40–60 task benchmark,
retries beyond the limits below, or any deployment/push. Any further paid run
needs a new explicit authorization.

## Provider and endpoint

The root `.env` currently sets:

```text
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.1-flash-lite
LLM_API_KEY=SET (35 chars, sk-…)
```

A free `GET https://api.deepseek.com/models` call with that key returned HTTP
200 and listed `deepseek-flash` and `deepseek-v4-pro`. The same key against the
Gemini endpoint returned HTTP 400 “Please pass a valid API key”. The configured
key is therefore a DeepSeek key and the existing provider/model lines do not
match it. The smoke uses process-level overrides and **does not modify the root
`.env` or the main workspace**:

```text
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-flash
SEARCH_PROVIDER=tavily
```

Search uses the existing `TAVILY_API_KEY` (prefix `tvly`). `SUPPORTING_PROVIDER`
is not used.

## Prices (read from the providers' current pages on 2026-11-20)

DeepSeek — <https://api-docs.deepseek.com/quick_start/pricing>:

| Item | Off-peak | Peak |
| --- | --- | --- |
| Input, cache hit (per 1M) | $0.003 | $0.006 |
| Input, cache miss (per 1M) | $0.15 | $0.30 |
| Output (per 1M) | $0.60 | $1.20 |

Peak hours are 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday. The smoke starts
at 2026-11-19 23:43 UTC (Thursday), i.e. **off-peak**. The planner still budgets
at peak rates.

Tavily — <https://www.tavily.com/pricing> and
<https://docs.tavily.com/documentation/api-credits>:

- Free plan: 1,000 API credits/month.
- Pay as you go: $0.008 per credit.
- Basic search (`search_depth=basic`): 1 credit per request.

The smoke uses Tavily basic search. If the account still has free credits, the
marginal search cost is $0; the budget below assumes every search is paid.

## Run budget

| Bound | Limit |
| --- | --- |
| Research jobs | 1 |
| LLM calls | 3 total (1 tiny preflight + at most 2 job calls) |
| LLM output per call | ≤ 768 tokens |
| LLM input per call | ≤ 16,000 tokens (expected ≈ 2–3k) |
| LLM retries | 0 (client `max_attempts=1`) |
| Search requests | ≤ 24 |
| Results per search | ≤ 6 |
| Search retries | 0 (`max_attempts=1`) |
| Wall clock | 480 s guard; 600 s hard process timeout |
| Maximum estimated spend | **$0.25** |

Worst-case arithmetic at **peak** rates: 3 × 16k input × $0.30/M = $0.0144;
3 × 768 output × $1.20/M = $0.0028; 24 Tavily credits × $0.008 = $0.192.
Total ≤ $0.21, under the $0.25 cap. At off-peak rates the model cost is halved.

## Data sent

- The research query is the public Anji County bamboo-industry question.
- Search result titles, URLs and up to 500 characters per document may be sent
  to DeepSeek for industry-focus discovery.
- API keys are never logged, written into artifacts, or committed.
- No private data, credentials, or local files are sent.

## Stop conditions

Stop immediately and record the failure if any of these occurs:

- Authentication, model-not-found, quota, or repeated 5xx error.
- Any LLM or search call would exceed the caps above.
- Wall-clock guard or hard timeout.
- The job reports `mode_label != LIVE`, or the guard observes zero real
  provider calls (silent MOCK fallback).
- Any unexpected provider or endpoint is used.
- Estimated spend approaches $0.25.
- The run produces content that looks like it came from a non-public source.

## Success criteria

The smoke is `PASS` only if:

1. exactly one job reaches a terminal status;
2. `mode_label == LIVE`;
3. at least one real DeepSeek call and one real Tavily request were observed;
4. the job produces a report and the graph/report projections respond;
5. no budget-guard violation occurred.

`PARTIAL` is the honest result if the job succeeds but returns no usable live
sources or no `SUPPORTED` claim. This smoke does **not** satisfy M5 Live
evaluation, the 40–60 sealed task set, semantic Judge, or human adjudication.

## Second run budget (2026-11-20, “再跑一次”)

| Bound | Limit |
| --- | --- |
| Additional research jobs | 1 |
| LLM calls | 3 total (1 tiny preflight + at most 2 job calls) |
| LLM output per call | ≤ 2,048 tokens |
| LLM input per call | ≤ 16,000 tokens |
| LLM retries | 0 |
| Search requests | ≤ 24 |
| Results per search | ≤ 6 |
| Search retries | 0 |
| Wall clock | 480 s guard; 600 s hard process timeout |
| Maximum estimated spend | **$0.25** |
| Focus | explicit contract focus `竹产业` must survive discovery |
| Run root | `experiments/quality/live_smoke_20261120_second/` |

Worst-case arithmetic at peak: 3 × 16k input × $0.30/M = $0.0144;
3 × 2,048 output × $1.20/M = $0.0074; 24 Tavily credits × $0.008 = $0.192.
Total ≤ $0.214, under the $0.25 cap.

The same data, stop-condition and success-criteria rules apply. The first run
used $0.0578 at most (7 searches); the second run is expected to be in the same
range.

## Actual usage (2026-11-20)

The authorized smoke ran once. Job
`d367c9b277cf47d086d28f9824d661e5` finished `SUCCEEDED` / `NO_PROGRESS`
(`no_supported_claims`) in 30.6 s. The guard observed:

| Item | Actual | Cap |
| --- | --- | --- |
| LLM calls | 2 (preflight + discovery) | 3 |
| Prompt tokens | 2,848 | ~48,000 |
| Completion tokens | 771 | 2,304 |
| Tavily basic searches | 7 | 24 |
| Guard violations | 0 | 0 |
| Total elapsed (guard) | 47.89 s | 480 s |

Estimated cost:

- DeepSeek off-peak: 2,848 × $0.15/M + 771 × $0.60/M = **$0.00089**.
- Tavily: 7 credits × $0.008 = **$0.056** if paid; $0 if still on free credits.
- Worst-case total if Tavily was paid: **$0.0578**, well below the $0.25 cap.

Caveat: the discovery call produced exactly 768 completion tokens, i.e. it hit
the per-call output cap. The run then used the handler default focus
(`特色农业`) instead of the contract focus (`竹产业`), which is consistent with a
truncated discovery JSON falling back. The smoke therefore proves the Live
plumbing, not the best-case retrieval quality.

## Second run actual usage (2026-11-20)

The user then said “再跑一次”, authorizing one additional bounded smoke. The
run used the same provider and prices, with a 2,048-token output allowance and
the explicit-focus fix from `application/research.py`. Job
`fdf7f3e86d444419967124236c4cc1ad` finished `SUCCEEDED` / `NO_PROGRESS`
(`no_supported_claims`) in 28.9 s. The guard observed:

| Item | Actual | Cap |
| --- | --- | --- |
| LLM calls | 2 (preflight + discovery) | 3 |
| Prompt tokens | 3,103 | ~48,000 |
| Completion tokens | 841 | 6,144 |
| Discovery completion | 838 | 2,048 |
| Tavily basic searches | 7 | 24 |
| Guard violations | 0 | 0 |
| Total elapsed (guard) | 43.56 s | 480 s |

Estimated cost:

- DeepSeek off-peak: 3,103 × $0.15/M + 841 × $0.60/M = **$0.00097**.
- Tavily: 7 credits × $0.008 = **$0.056** if paid; $0 if still on free credits.
- Worst-case total if Tavily was paid: **$0.0579**, below the $0.25 cap.

The discovery call no longer hit its cap, and `stage.discover.completed` reports
`竹产业`, confirming the explicit-focus fix. The verifier still accepted zero
claims: 224 `NOT_COMPARABLE`, 7 conflicts, 2 gaps. The remaining blockers are
retrieval region relevance and period coverage, not focus selection.

## Third run budget (pre-registered, 2026-11-20)

Authorized by “跑第三次” after the deterministic region gate was implemented
and replayed offline. The budget is identical to the second run so the
comparison is clean:

| Item | Cap |
| --- | --- |
| Additional research jobs | 1 |
| LLM calls | 3 total (1 tiny preflight + at most 2 job calls) |
| LLM output per call | ≤ 2,048 tokens |
| LLM input per call | ≤ 16,000 tokens |
| LLM retries | 0 |
| Search requests | ≤ 24 |
| Results per search | ≤ 6 |
| Search retries | 0 |
| Wall clock | 480 s guard; 600 s hard process timeout |
| Maximum estimated spend | **$0.25** |
| Contract | `安吉县 竹产业`, 2024 window, explicit focus |
| Run root | `experiments/quality/live_smoke_20261120_third/` |

Worst-case arithmetic at peak: 3 × 16k input × $0.30/M = $0.0144;
3 × 2,048 output × $1.20/M = $0.0074; 24 Tavily credits × $0.008 = $0.192.
Total ≤ $0.214, under the $0.25 cap.

Expected region-gate evidence: `retrieval.round.completed` usage must report
`region_filtered_documents > 0`, and every persisted source must classify as
`REGION` or `UNKNOWN` (no `NATIONAL`/`OTHER_REGION`/`CONTEXT` pages). The
verifier may still accept zero claims because the 2024 period coverage is not
part of this fix; that would not fail the engineering verdict.

Stop conditions are unchanged: any guard violation, non-`SUCCEEDED` terminal
state, or an unexpected provider error ends the run and is recorded honestly.

## Third run actual usage (2026-11-20)

The user said “跑第三次” after the region gate was implemented. Job
`007487e8e7494e3fba1770c1f7b0781f` finished `SUCCEEDED` / `LIVE` /
`NO_PROGRESS` (`no_supported_claims`) in 29.2 s. The guard observed:

| Item | Actual | Cap |
| --- | --- | --- |
| LLM calls | 2 (preflight + discovery) | 3 |
| Prompt tokens | 3,466 | ~48,000 |
| Completion tokens | 1,227 | 6,144 |
| Discovery completion | 1,224 | 2,048 |
| Tavily basic searches | 7 | 24 |
| Guard violations | 0 | 0 |
| Total elapsed (guard) | 29.23 s | 480 s |

Estimated cost:

- DeepSeek off-peak: 3,466 × $0.15/M + 1,227 × $0.60/M = **$0.001256**.
- Tavily: 7 credits × $0.008 = **$0.056** if paid; $0 if still on free credits.
- Worst-case total if Tavily was paid: **$0.0585**, below the $0.25 cap.

Result: 28 events, 165 graph nodes / 1,077 edges (800 returned), 8 sources,
0 verified / 133 `NOT_COMPARABLE`, 6 conflicts, 2 gaps. The gate kept seven
Anji-related sources and let one false positive through: the Guizhou five-year
plan contains “安吉精铸” and “正安吉他”, which the short-name substring rule
mistook for the county. The classifier was fixed to require the full
`安吉县` inside document content and to match the short name only on a word
boundary in title/snippet/URL; replaying this run's stored sources marks the
Guizhou plan `OTHER_REGION`. No provider calls were made for that replay, and
no fourth run was made.
