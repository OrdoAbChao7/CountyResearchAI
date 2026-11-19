# Live Smoke Cost Gate — 2026-11-20

Status: `AUTHORIZED_FOR_ONE_BOUNDED_SMOKE`

## Authorization

The user explicitly authorized paid provider calls and asked for one Live run:

- 2026-11-20: “需要api我可以提供ds 的api在根目录的.env文件夹下面，允许付费调用”
- 2026-11-20: “跑一次 Live”

This authorization covers **one** bounded smoke run only. It does not authorize a
Live evaluation campaign, a semantic Judge, a 40–60 task benchmark, retries
beyond the limits below, or any deployment/push.

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
plumbing, not the best-case retrieval quality. A second run with a larger
discovery allowance requires a fresh authorization.

No further paid calls were made after this run.

