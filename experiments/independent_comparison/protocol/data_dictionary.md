# Data Dictionary

| Field | Meaning | Required |
| --- | --- | --- |
| `run_id` | Single isolated research run identifier | yes |
| `experiment_id` | `E1` end-to-end or `E2` fixed-input analysis | yes |
| `group` | A/B/C for research runs; anonymous for judging | yes |
| `region` | Frozen administrative region name and level | yes |
| `task_id` | `snapshot`, `rise-fall` or `long-history` | yes |
| `model` | Frozen provider model id | yes |
| `formal_target` | Explicit boolean marker required for formal E1/E2 post-run scoring; absent/false means development or historical run | yes for new formal manifests |
| `status` | `VALID`, `INVALID_*`, `FAILED`, `BLOCKED`, `NOT_RUN` | yes |
| `config_hash` | Hash of frozen config, budget and prompt version | yes |
| `prompt_tokens` | Provider-returned input usage; null if unavailable | conditional |
| `completion_tokens` | Provider-returned output usage; null if unavailable | conditional |
| `tavily_credits` | Request credit accounting | conditional |
| `duration_seconds` | End-to-end wall time from RUNNING to terminal status | yes for executed runs |
| `resource_usage` | Per-provider/model/kind actual settled units for this run | yes for executed runs |
| `claim_id` | Declaration-level claim identifier | yes for judging |
| `support_status` | `SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`, `DISPUTED`, `UNVERIFIED` | yes for judging |

## Statistics Input

The statistics generator consumes one JSON object per run. It requires `status: VALID`, `metrics` with `fact_accuracy`, `key_fact_coverage`, `evidence_support_rate`, and `error_rate`, plus `run_id`, `group`, `region`, `task_id`, and `repeat`. `analysis_depth` and `report_qa_accuracy` are populated after Judge and Report-Based QA; `duration_seconds` and `resource_usage` are used to derive wall time, LLM tokens, search requests, and coverage per LLM token. Invalid or non-`VALID` runs remain in the audit ledger and are excluded from quality summaries; if no valid rows exist, the generator writes `NO_VALID_METRICS` and no figures.

Report-Based QA answers are generated from the frozen questions in `protocol/report_qa_questions_20261018.yaml`; the answer Agent receives only an anonymized report and question. The conservative numeric scorer runs after the answer is archived and reads the frozen Ground Truth separately. The statistics generator writes both group-level summaries and `region_summary.csv` with one region×group breakdown per metric; `region_<metric>.svg` figures are generated only when valid observations exist.

## Ground Truth Claim

Ground Truth JSONL records must include `claim`, `source`, `url`, `date`, `region`, `metric`, `unit`, `evidence_excerpt`, `confidence`, and `verification_status`. A `VERIFIED` claim additionally requires at least two distinct `verification_sources` and two distinct `verification_contexts`. The source excerpt must be stored independently of the research-group reports and frozen before scoring. Formal QA and Claim scoring must call `GroundTruthStore.freeze_verified` and reject a missing/non-formal/floating manifest or a `source_hash` mismatch before reading claims.
