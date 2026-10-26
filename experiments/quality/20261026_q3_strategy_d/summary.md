# Strategy D offline evaluation

Generated: 2026-10-26T11:53:07.687680+00:00 · provider calls 0

| Condition | Retrieved | Supported | Answered | E2E |
| --- | ---: | ---: | ---: | ---: |
| C legacy report | 21 | 8 | 4 | 0.033 |
| D old grouping | 21 | 2 | 2 | 0.022 |
| D measure-aware | 21 | 15 | 16 | 0.167 |
| D no verifier | 21 | — (655 unsupported included) | 16 | 0.178* |

*No-verifier answer coverage is not comparable to verified E2E: it includes unsupported statements and is shown as a precision-risk upper bound.

## D measure-aware funnel

`{'not_extracted': 6, 'not_retrieved': 69, 'success': 15}`

## Caveats

- D answers are deterministic extracts, not fluent reports; this measures fact coverage, not prose quality.
- Retrieval is fixed to the archived documents; D cannot recover facts the collector never fetched.
- Dev replay only; the blind pilot was not read and cannot be used for tuning.
- No provider or semantic judge was used.
