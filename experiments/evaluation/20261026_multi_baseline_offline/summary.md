# Multi-baseline offline comparison

Generated: 2026-10-26T10:00:07.817489+00:00
Evidence kind: `OFFLINE_REPLAY` · provider calls: 0
Observations SHA-256: `4341ea07abbaa5495565052e7d8fd3a5a35eb03063f45b09680a0481142d5c1e`

| Group | Valid runs | GT recall (mean) | Support precision (pooled) | Fact accuracy | Error rate | LLM units/run | Seconds/run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A 传统检索模拟 + 单次 LLM 合成 | 18 | 0.16 | 0.1875 (12/64) | 0.2267 | 0.7733 | 6608.3 | 41.43 |
| B 通用联网 AI | 18 | 0.1222 | 0.1358 (11/81) | 0.1667 | 0.8333 | 6895.2 | 42.12 |
| C CountyResearchAI 旧管线 | 12 | 0.0333 | 0.0357 (2/56) | 0.0417 | 0.9583 | 22651.7 | 77.68 |

## Paired comparisons

- **A vs C**: 12 paired cases, mean recall delta 0.1667, 5 wins / 6 ties / 1 losses for A.
- **B vs C**: 12 paired cases, mean recall delta 0.15, 4 wins / 7 ties / 1 losses for B.

## Not measured

- `D`: full AxiomScope v2 not run on this corpus
- `live`: BLOCKED_EXTERNAL: no new provider/Judge cost authorization
- `ablations`: NOT_RUN: no graph/semantic-verifier/gap-research/hybrid ablation
- `independent_task_set`: NOT_RUN: this corpus is the inherited frozen set, not a newly curated 40-60 task holdout

## Caveats

- Small sample; no statistical significance is claimed.
- C has 12 valid runs; six long-history runs exceeded the 120s budget and are excluded from means.
- All metrics are deterministic offline rescoring of frozen outputs.
- The report cannot establish that AxiomScope v2 beats any baseline.
