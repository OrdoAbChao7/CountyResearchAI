# Cost Gate — Quality Recovery

Status: `NO_PAID_CALLS_AUTHORIZED` / live E2E `BLOCKED_EXTERNAL`

## Current rule

No paid Provider, semantic Judge, or other paid API may be called without the
user's explicit cost authorization. All Q0/Q1 work and planned Q2/Q3 work is
offline, deterministic, and free.

## Why paid calls would be needed

| Work | Needs paid calls? | Current status |
| --- | --- | --- |
| Q1 stage attribution | No (archived docs/reports) | DONE offline |
| Q2 dataset curation | No (existing archived/real URLs; hash and quote) | offline |
| Q3 Strategy D (retrieval/identity/answer rules) | No | offline |
| Q4 A/B/C/D offline paired runs | No | offline |
| Q4 live end-to-end confirmation | Yes (search + LLM) | BLOCKED_EXTERNAL |
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
