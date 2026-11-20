# Cost Gate — Quality Recovery

Status: `THREE_SMOKES_AUTHORIZED_2026-11-20` / live evaluation still `NOT_AUTHORIZED`

## Current rule

No paid Provider, semantic Judge, or other paid API may be called without the
user's explicit cost authorization. All Q0/Q1 work and planned Q2/Q3 work is
offline, deterministic, and free.

The user authorized **one** bounded Live smoke on 2026-11-20 (“允许付费调用”,
“跑一次 Live”), then authorized **one additional** bounded smoke (“再跑一次”)
after the first run exposed a truncated discovery response, then a **third**
(“跑第三次”) to verify the region gate against a real provider. All three ran
and are recorded in [LIVE_SMOKE.md](LIVE_SMOKE.md). The recorded budget,
prices, provider override and stop conditions are in
[LIVE_SMOKE_COST_GATE.md](LIVE_SMOKE_COST_GATE.md). That authorization does not
extend to a fourth run, a Live evaluation campaign, a semantic Judge, or the
40–60 task benchmark.

## Why paid calls would be needed

| Work | Needs paid calls? | Current status |
| --- | --- | --- |
| Q1 stage attribution | No (archived docs/reports) | DONE offline |
| Q2 dataset curation | No (existing archived/real URLs; hash and quote) | offline |
| Q3 Strategy D (retrieval/identity/answer rules) | No | offline |
| Q4 A/B/C/D offline paired runs | No | offline |
| Q4 live end-to-end confirmation | Yes (search + LLM) | PARTIAL — three bounded smokes on 2026-11-20; no Live evaluation |
| Independent semantic Judge | Yes | BLOCKED_EXTERNAL |
| Playwright E2E | No (local MOCK) | install/browser download only |

## If live evaluation is requested

Before any call, record: provider, model, per-call token price, number of runs,
retry allowance, maximum spend, and stop conditions. Do not invent prices; read
the provider's current pricing page. Until then, live results stay `BLOCKED`
and are never estimated or simulated as live.

## Forbidden

- Sending API keys, source content, or private data to an unapproved service.
- Replacing offline/fixture evidence with fabricated live numbers.
- Spending to improve a metric without a pre-registered budget and comparison.
