# Claim Verification batch failure

This batch is retained as a failed audit artifact and is excluded from quality metrics.

- Batch: `claims_formal_target_deepseek_20261018`
- Completed and settled leases: 24
- Overrun leases: 1
- Failure: one DeepSeek response settled at 3,109 tokens after the per-lease reservation of 1,024, exceeding the batch capacity of 36,864 units.
- No `claim_observations.jsonl` was emitted, so no partial score is treated as complete.
- Recovery: rerun all 36 formal candidates under a new batch id with a larger accounting capacity; do not resume this directory.
