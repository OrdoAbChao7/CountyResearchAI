# Quality Recovery Artifacts

All results are offline. No paid Provider or semantic Judge calls were made.

| Directory | Meaning |
| --- | --- |
| `20261026_baseline/` | Q0 test/ruff/frontend logs and environment |
| `20261026_q1_funnel_baseline/` | Q1 funnel **before** Strategy D (2 supported, 0 E2E, 872 withheld source) |
| `20261026_q1_withheld_review_baseline/` | Q1 withheld review **before** measure identity (872; 351 different-measure) |
| `20261026_q3_measure_identity_funnel/` | same funnel **after** measure identity + period inference (15 supported, 15/90 E2E) |
| `20261026_q3_measure_identity_withheld/` | withheld review after measure identity (203; 23 different-measure) |
| `20261026_q3_strategy_d/` | dev-replay A/B/C/D conditions and no-verifier ablation |
| `20261026_q4_ablations/` | BM25 vs adaptive replay |
| `20261026_q4_blind_pilot/` | locked 2-task / 10-fact blind pilot |
| `dataset/` | Q2 dev/blind manifest, exact quotes, hashes, validation |

The baseline directories were restored from commit `3a07aea`; later reruns write
to the Q3 directories. `summary.json` files include generation timestamps and
hashes. Do not treat the two funnel files as one time series without checking
the directory names.

## Q7 directories

| Directory | Meaning |
| --- | --- |
| `20261026_q7_corpus/` | full archived corpus coverage and missing-fact list |
| `20261026_q7_retrieval/` | autonomous free-web search, query logs, hit snapshots |
| `20261026_q7_oracle_probe/` | GT-URL source-availability ceiling (diagnostic only) |
| `20261026_q7_verifier_audit/` | stratified sample, assistant labels, confusion matrix |
| `20261026_q7_pooled_eval/` | Strategy D over pooled archived corpus |
| `20261026_q7_pooled_free_eval/` | pooled corpus + free-web hits |
| `20261026_q7_bootstrap/` | task-clustered bootstrap, dev only |
| `20261026_q7_stress/` | two-process lease/fencing stress log and summary |

Q7 retrieval cache directories are gitignored; summaries and hit snapshots are
committed. Assistant audit labels are not human ground truth.
