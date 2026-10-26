# Q2 Evaluation Dataset

Status: `DEV_REPLAY + BLIND_PILOT`, coverage gap recorded. No fabricated tasks.

## Splits

### Dev replay (not independent)

- Source: `experiments/independent_comparison/ground_truth/continuation_ground_truth_20261019.jsonl`
- SHA-256: recorded in `experiments/quality/dataset/validation.json`
- 18 tasks (6 regions × 3 modes), 90 facts.
- Used for Q1 diagnosis and Q3 tuning. **Not a blind set.**

### Blind pilot (disjoint, validated)

- File: `experiments/quality/dataset/blind_pilot.jsonl`
- SHA-256: recorded in `validation.json`
- Tasks: 2 snapshot tasks, 10 facts.
  - 安吉县 2025: GDP 710.60亿元, 第三产业 342.24亿元, 规上工业 249.12亿元,
    一般公共预算收入 63.36亿元.
  - 信丰县 2025/2024: 脐橙种植面积 28.5万亩, 产量 28.6万吨, 集群总产值 70亿元,
    加工产值 20亿元, 线上销售额 3.6亿元, 1971年引种.
- Regions 安吉县/信丰县 do not appear in the inherited 18-task set.
- Every fact has: exact quote, source URL, source title, archived snapshot path,
  document index, value, unit, period, expected answer, snapshot SHA-256, quote
  SHA-256, and a manual annotation label.
- Not used in Q1 diagnosis or Q3 development.

## Validation

```powershell
.venv\Scripts\python.exe -m scripts.validate_quality_dataset
```

Checks: snapshot exists and hashes; document URL matches; quote is an exact
substring; value+unit resolves in the quote; expected answer contains the value;
period is evidenced by quote/title/URL/published date; dev and blind task keys
do not overlap. Result: `VALIDATED_BLIND_PILOT`, 10/10 facts valid.

Two candidate facts (安吉 第一/第二产业增加值) were removed because the source
uses a shared trailing unit (`36.51、331.85和342.24亿元`); the strict validator
cannot attribute the shared unit to each value. This is a real extraction
limitation (defect D5), not a reason to relax the dataset.

## Coverage gap (honest)

| Target | Achieved | Gap |
| --- | ---: | ---: |
| 40–60 independent blind tasks | 2 blind tasks / 10 facts | 38–58 tasks |
| 18 dev tasks (inherited) | 18 | not independent |

Why the gap: the repository contains verified exact-quote facts for only the 18
inherited tasks. The only disjoint archived snapshots with verifiable quotes are
the Anji and Xinfeng runs. Reaching 40–60 requires either (a) new free/paid
retrieval plus human annotation, or (b) additional archived sources that meet the
same quote/hash standard. No paid search or annotation was authorized, and no
tasks were duplicated or relabelled to inflate the count.

## Leakage controls

- Blind regions are disjoint from dev regions.
- Q1/Q3 development must not read `blind_pilot.jsonl` except through the
  validator; the manifest records `blind_used_in_q1: false`.
- If Q3 is tuned after seeing blind results, those results become dev and the
  blind status must be revoked in a new manifest version.
