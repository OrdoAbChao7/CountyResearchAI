# Q1 Quality Funnel — Strategy C

Generated: 2026-10-26T11:31:09.923222+00:00
Evidence: offline archived docs/reports; provider calls 0.

| Run | Docs | Claims | Retrieval | Extraction | Supported | Answered | E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 德清县 long-history | 2 | 101 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 德清县 rise-fall | 2 | 153 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 德清县 snapshot | 2 | 231 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| 长汀县 long-history | 2 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 长汀县 rise-fall | 2 | 33 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 长汀县 snapshot | 2 | 178 | 0.200 | 0.200 | 1.000 | 0.000 | 0.000 |
| 于都县 long-history | 2 | 6 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 于都县 rise-fall | 2 | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 于都县 snapshot | 2 | 91 | 0.200 | 0.200 | 1.000 | 0.200 | 0.200 |
| 攀枝花市 long-history | 2 | 11 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 攀枝花市 rise-fall | 2 | 16 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 攀枝花市 snapshot | 2 | 43 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 白山市 long-history | 2 | 32 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 白山市 rise-fall | 2 | 129 | 1.000 | 0.600 | 1.000 | 0.400 | 0.400 |
| 白山市 snapshot | 2 | 81 | 0.800 | 0.000 | 0.000 | 0.000 | 0.000 |
| 临泽县 long-history | 2 | 17 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 临泽县 rise-fall | 2 | 15 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 临泽县 snapshot | 2 | 133 | 1.000 | 1.000 | 1.000 | 0.200 | 0.200 |

## Overall

- Claims: 90
- Retrieved: 21 (23.3%)
- Recall@1/3/5: 0.167 / 0.233 / 0.233; MRR 0.200
- Extracted: 15 (16.7%)
- Supported among extracted: 15 (100.0%)
- Answered: 4 (4.4%)
- End-to-end: 4 (4.4%)
- Funnel: `{'not_extracted': 6, 'not_in_answer': 11, 'not_retrieved': 69, 'success': 4}`

## Caveats

- Retrieval uses archived raw documents only; it is a retrieval-set coverage proxy, not a live search benchmark.
- Extraction matching is deterministic and GT-anchored; unmatched claims are not automatically wrong.
- A withheld claim is labelled a candidate false rejection only when the exact GT excerpt is in its own span; all others need review.
- No semantic judge or human labels were used.
