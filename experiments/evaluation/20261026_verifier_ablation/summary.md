# Verifier ablation on frozen C archives

Generated: 2026-10-26T09:54:53.095055+00:00
Evidence kind: `OFFLINE_VERIFIER_ABLATION` · provider calls: 0

> Same extracted claims and raw text; compares legacy verification with the deterministic v2 verifier. Not an end-to-end quality result.

| Metric | Value |
| --- | ---: |
| Runs | 18 |
| Extracted claims | 1275 |
| Legacy `verified` | 495 |
| Deterministic objective support (value/span checks) | 1243 |
| Deterministic `SUPPORTED` after conflict resolution | 173 |
| Withheld by a supported conflict (`NEEDS_REVIEW`) | 998 |
| Downgraded (legacy verified → not supported) | 417 |
| Upgraded (legacy unverified → supported) | 95 |

## Reasons

| Reason | Claims |
| --- | ---: |
| `conflicting_supported_evidence` | 998 |
| `no_evidence` | 2 |
| `numeric_value_without_period` | 72 |
| `statement_exact_in_span` | 134 |
| `statement_not_in_span` | 30 |
| `value_and_span_verified` | 39 |

## Cases

| Run | Claims | Legacy verified | Objective support | Supported | Withheld by conflict | Downgraded | Upgraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| continuation_matched_budget_deepseek_flash_20261019_region_01_long-history_r1_C | 101 | 0 | 97 | 4 | 93 | 0 | 4 |
| continuation_matched_budget_deepseek_flash_20261019_region_01_rise-fall_r1_C | 153 | 0 | 152 | 11 | 141 | 0 | 11 |
| continuation_matched_budget_deepseek_flash_20261019_region_01_snapshot_r1_C | 231 | 140 | 231 | 30 | 201 | 116 | 6 |
| continuation_matched_budget_deepseek_flash_20261019_region_02_long-history_r1_C | 3 | 2 | 0 | 0 | 0 | 2 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_02_rise-fall_r1_C | 33 | 33 | 31 | 19 | 0 | 14 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_02_snapshot_r1_C | 178 | 0 | 178 | 26 | 152 | 0 | 26 |
| continuation_matched_budget_deepseek_flash_20261019_region_03_long-history_r1_C | 6 | 1 | 6 | 2 | 0 | 0 | 1 |
| continuation_matched_budget_deepseek_flash_20261019_region_03_rise-fall_r1_C | 2 | 1 | 1 | 1 | 0 | 1 | 1 |
| continuation_matched_budget_deepseek_flash_20261019_region_03_snapshot_r1_C | 91 | 10 | 90 | 10 | 80 | 8 | 8 |
| continuation_matched_budget_deepseek_flash_20261019_region_04_long-history_r1_C | 11 | 11 | 9 | 0 | 0 | 11 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_04_rise-fall_r1_C | 16 | 11 | 12 | 3 | 0 | 11 | 3 |
| continuation_matched_budget_deepseek_flash_20261019_region_04_snapshot_r1_C | 43 | 43 | 41 | 4 | 28 | 39 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_05_long-history_r1_C | 32 | 26 | 26 | 1 | 0 | 25 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_05_rise-fall_r1_C | 129 | 129 | 129 | 16 | 113 | 113 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_05_snapshot_r1_C | 81 | 81 | 81 | 10 | 71 | 71 | 0 |
| continuation_matched_budget_deepseek_flash_20261019_region_06_long-history_r1_C | 17 | 1 | 15 | 8 | 3 | 1 | 8 |
| continuation_matched_budget_deepseek_flash_20261019_region_06_rise-fall_r1_C | 15 | 1 | 12 | 9 | 3 | 1 | 9 |
| continuation_matched_budget_deepseek_flash_20261019_region_06_snapshot_r1_C | 133 | 5 | 132 | 19 | 113 | 4 | 18 |

Caveats: only group C archives with raw documents are included. This measures verifier behavior, not report or retrieval quality. Legacy claim identity is coarse (many different statements share metric/period/scope), so the conflict layer withholds many claims as `NEEDS_REVIEW`; that is a data-quality finding about the legacy extractor, not evidence that the verifier is correct on every case.
