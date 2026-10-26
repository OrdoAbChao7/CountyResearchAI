# Q1 withheld-claim review

Generated: 2026-10-26T11:21:16.366087+00:00 · provider calls 0

- Withheld `NEEDS_REVIEW`: 872
- Categories: `{'different_measure_grouped_conflict': 351, 'same_measure_value_conflict': 521}`
- Conflict-count distribution: `{1: 12, 2: 9, 5: 2, 6: 5, 9: 2, 10: 9, 12: 2, 13: 12, 16: 34, 17: 18, 18: 38, 20: 21, 22: 23, 51: 12, 52: 41, 55: 14, 56: 43, 63: 10, 64: 55, 70: 18, 71: 54, 85: 3, 86: 14, 87: 71, 93: 6, 94: 89, 118: 18, 119: 102, 130: 5, 132: 3, 133: 34, 134: 93}`
- Supported but statement not in quote: 0

## By mode

- long-history: `{'different_measure_grouped_conflict': 39, 'same_measure_value_conflict': 54}`
- rise-fall: `{'same_measure_value_conflict': 176, 'different_measure_grouped_conflict': 75}`
- snapshot: `{'different_measure_grouped_conflict': 237, 'same_measure_value_conflict': 291}`

## Notes

- different_measure_grouped_conflict means the conflicting claims share region/metric/period/scope/caliber identity but state different measures; this is a coarse-identity grouping problem, not proof of a false rejection in every case.
- supported_by_metric_only lists SUPPORTED claims whose exact statement was not found in the quote (metric-only support); these are candidates for false support, not confirmed errors.
- No human labels or semantic judge were used.
