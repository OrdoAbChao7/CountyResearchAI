# Q1 withheld-claim review

Generated: 2026-10-26T11:30:39.005370+00:00 · provider calls 0

- Withheld `NEEDS_REVIEW`: 203
- Categories: `{'different_measure_grouped_conflict': 23, 'same_measure_value_conflict': 180}`
- Conflict-count distribution: `{1: 49, 2: 12, 4: 4, 5: 6, 19: 19, 34: 35, 56: 1, 76: 77}`
- Supported but statement not in quote: 0

## By mode

- long-history: `{'different_measure_grouped_conflict': 4}`
- rise-fall: `{'same_measure_value_conflict': 123}`
- snapshot: `{'same_measure_value_conflict': 57, 'different_measure_grouped_conflict': 19}`

## Notes

- different_measure_grouped_conflict means the conflicting claims share region/metric/period/scope/caliber identity but state different measures; this is a coarse-identity grouping problem, not proof of a false rejection in every case.
- supported_by_metric_only lists SUPPORTED claims whose exact statement was not found in the quote (metric-only support); these are candidates for false support, not confirmed errors.
- No human labels or semantic judge were used.
