# Q7 task-clustered bootstrap

Tasks: 18 · iterations 4000

- **D_pooled_minus_C**: mean 0.3333 (95% [0.1556, 0.5222]), 9 / 9 / 0
- **D_archived_minus_C**: mean 0.1333 (95% [0.0222, 0.2778]), 5 / 13 / 0
- **D_pooled_free_minus_C**: mean 0.3111 (95% [0.1444, 0.4889]), 9 / 9 / 0
- **D_pooled_minus_D_archived**: mean 0.2 (95% [0.0667, 0.3667]), 6 / 12 / 0
- **D_pooled_free_minus_D_pooled**: mean -0.0222 (95% [-0.0667, 0.0]), 0 / 17 / 1

## Caveats

- 18 task clusters, dev replay only; not a sealed holdout.
- Task-level E2E is the mean of correlated facts within the task.
- Bootstrap over tasks; small n means intervals are wide.
- No paid provider or judge calls.
