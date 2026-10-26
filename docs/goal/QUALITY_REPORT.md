# Quality Recovery Report

Updated: 2026-10-26 · branch `codex/quality-recovery`
Evidence kinds: tests, offline archived replay, offline stage diagnosis. No paid
Provider or semantic Judge calls.

## Q0 — Baseline

| Check | Result | Artifact |
| --- | --- | --- |
| Checkpoint | tag `checkpoint-m4-pass-20261026`, branch `codex/quality-recovery` | git |
| Python | 675 passed, 1 warning | `experiments/quality/20261026_baseline/pytest.txt` |
| Ruff `src tests` | clean | `ruff_scoped.txt` |
| Ruff full tree | 73 historical findings (scripts/_verify_*) | `ruff.txt` |
| Frontend | typecheck clean, 4 tests, build 161 kB JS | `frontend_*.txt` |
| Environment | Python 3.13.7, Node 24.19.0, npm 11.17.0 | `env.txt` |

M0–M4 code paths were not rewritten; `.claude/` was left untouched.

## Q1 — Stage diagnosis (Strategy C, frozen archives)

Inputs: 18 archived C runs (6 regions × 3 modes), 90 frozen ground-truth facts,
archived raw documents and final reports. Output:
`experiments/quality/20261026_q1_funnel/`.

| Stage | Count | Rate |
| --- | ---: | ---: |
| Required facts | 90 | 100% |
| Retrieved in C's raw docs | 21 | 23.3% |
| Extracted as claims | 15 | 16.7% |
| Deterministically SUPPORTED | 2 | 2.2% overall; 13.3% of extracted |
| Present in final report | 4 | 4.4% |
| End-to-end (supported + reported) | 0 | 0% |

Retrieval: Recall@1 0.167, Recall@3 0.233, Recall@5 0.233, MRR 0.200.

| Mode | Claims | Retrieved | Extracted | Supported | Answered | E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| snapshot | 30 | 16 (53.3%) | 12 (40.0%) | 2 | 2 | 0 |
| rise-fall | 30 | 5 (16.7%) | 3 (10.0%) | 0 | 2 | 0 |
| long-history | 30 | 0 (0%) | 0 | 0 | 0 | 0 |

Funnel labels: `not_retrieved` 69, `not_extracted` 6,
`withheld_exact_evidence` 12, `withheld_other` 1, `not_in_answer` 2,
success 0.

### Root causes (ranked by observed impact)

1. **Retrieval coverage is the dominant bottleneck.** 69/90 facts never appear in
   C's own archived documents; long-history is 0/30. The report cannot recover
   facts the collector never fetched. This is a query-planning and
   temporal-retrieval failure, not a verifier failure.
2. **Coarse, decontextualized claim identity.** 872/1,275 claims are withheld as
   `conflicting_supported_evidence`. Classification over the full corpus:
   351 have only different-measure conflicts; 521 have at least one
   same-string measure conflict, but the strings are frequently truncated
   fragments such as `增长4.3%` or shared buckets such as `产值与收入`.
   Examples: `第一产业增加值33.0亿元` conflicts with `第二产业增加值385.9亿元`,
   `装备制造业增加值138.8亿元`, and `农林牧渔业增加值34.9亿元`, because all share
   `metric_id=产值与收入`. These are different measures, not contradictions.
3. **Decontextualized extraction.** Many claims are sentence fragments without
   their subject (`增长4.3%`, `同比增长6.0%`), so even a correct value cannot be
   attributed to a measure. This makes the identity problem above unavoidable.
4. **Verified claims are disconnected from the final answer.** Two claims were
   SUPPORTED (德清 GDP 722.5亿元; 于都 一般公共预算收入 3.01亿元), but neither value
   appears in the corresponding report. Four report facts were correct but not
   extracted/verified. The generation path does not consume the verified claims.
5. **Extraction misses 6 of 21 retrieved facts**; extraction recall among
   retrieved is 71.4%, better than retrieval but still material.
6. **False-support risk is unmeasured, not absent.** A scan found 0 SUPPORTED
   claims whose exact statement was absent from the quote, but GT is not
   exhaustive. No claim of low false-support rate is made.

### Withheld review

`experiments/quality/20261026_q1_withheld_review/summary.json`:
- withheld `NEEDS_REVIEW`: 872
- different-measure grouped conflicts: 351
- same-string measure conflicts: 521
- supported-but-statement-not-in-quote: 0 (30-claim sample available)

The 12 GT-matched withheld claims all have the exact GT excerpt in their own
span and are withheld because different measures share a coarse metric id. These
are **candidate false rejections**, confirmed only for the inspected cases; the
remaining 860 are unlabelled.

## Defect list (impact-ranked)

| ID | Defect | Evidence | Planned fix |
| --- | --- | --- | --- |
| D1 | Retrieval coverage / temporal query planning | 69/90 not retrieved; long-history 0/30 | temporal-aware queries, gap-driven retrieval |
| D2 | Coarse conflict grouping | 872 withheld; 351 different-measure-only | measure-aware relation keys |
| D3 | Decontextualized claim statements | `增长4.3%` fragments | enrich with nearest subject/measure |
| D4 | Verified findings not used in answer | 2 supported, 0 reported | generate from verified findings |
| D5 | Extraction misses retrieved facts | 6/21 | extraction rules/eval |
| D6 | No labelled false-support audit | 0 metric-only supports; GT not exhaustive | independent audit sample |

## Q3 implementation order (evidence-driven)

1. **D2/D3 first** — offline, deterministic, directly unblocks 872 withheld claims
   without loosening any truth check.
2. **D4** — make Strategy D answer from verified findings.
3. **D1/D5** — temporal/gap retrieval and extraction improvements, measured on a
   dev set before the blind set.

## Status

Q0 PASS. Q1 PASS (diagnosis complete; unlabelled items labelled as such).
Q2–Q6 remain. No quality improvement is claimed yet.
