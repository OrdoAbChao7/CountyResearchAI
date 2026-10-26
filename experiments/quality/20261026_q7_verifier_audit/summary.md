# Verifier audit

Sample: 25 · labelers: {'assistant_manual_review': 25}
Human ground truth: False

| Status | correct | incorrect |
| --- | ---: | ---: |
| INSUFFICIENT | 1 | 4 |
| NEEDS_REVIEW | 10 | 0 |
| SUPPORTED | 7 | 3 |

- False support: 3/10 = 0.3 (Wilson (0.1078, 0.6032))
- False rejection: 4/15 = 0.2667 (Wilson (0.109, 0.5195))
- Error types: `{'false_rejection_period_metadata': 2, 'false_rejection_wrong_span_link': 2, 'false_support_fragment_wrong_measure': 1, 'false_support_period_mismatch': 1, 'false_support_sign_measure_mismatch': 1}`

## Caveats

- Labels are assistant manual review, not human ground truth.
- Stratified sample (10 SUPPORTED, 15 rejected); not population-weighted.
- Rates describe this sample and do not estimate the full claim population.
- The sample frame had no OUTDATED or NOT_COMPARABLE claims.
