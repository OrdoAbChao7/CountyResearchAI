# Q3/Q4 — Strategy D, ablations, and blind pilot

Updated: 2026-10-26 · branch `codex/quality-recovery`
Evidence: offline archived replay and deterministic extraction. No provider or
Judge calls.

Artifacts:
`experiments/quality/20261026_q3_measure_identity_funnel/`,
`20261026_q3_measure_identity_withheld/`,
`20261026_q3_strategy_d/`, `20261026_q4_blind_pilot/`,
`20261026_q4_ablations/`. Pre-Q3 Q1 baselines are preserved under
`20261026_q1_funnel_baseline/` and `20261026_q1_withheld_review_baseline/`.

## Q3 implementation (evidence-driven order)

1. **Context-aware measure identity** (`evidence/measure.py`): derive a measure
   from the statement, or from the source window before the value when the
   statement is a fragment (`增长4.3%`). Canonicalize aliases (`一产` →
   `第一产业`, `规上` → `规模以上`). `AtomicClaim.measure_id` is persisted.
2. **Conflict grouping** (`classify_claim_relation`): different measure keys are
   `RELATED`, not `CONTRADICTED`. `use_measure_identity=False` preserves the old
   behavior for ablation.
3. **Period inference** (`infer_period`): when the extractor leaves the period
   empty, use statement year → year near the value → title year → publication
   date → document header. It never invents a year.
4. **Verified answer** (`application/verified_answer.py`): Strategy D answers
   only from run-scoped `SUPPORTED` findings, with measure + statement + value +
   unit + period and a source URL. This is deterministic and extractive; it is
   not a fluent report.

## Dev-replay results (18 inherited tasks / 90 GT facts)

| Condition | Retrieved | Supported GT facts | Answered | E2E | 95% Wilson CI |
| --- | ---: | ---: | ---: | ---: | --- |
| C legacy report | 21 | 8 legacy verified | 4 | 3/90 (3.3%) | 1.1–9.3% |
| D old grouping | 21 | 2 | 2 | 2/90 (2.2%) | 0.6–7.7% |
| D measure-aware | 21 | 15 | 16 | 15/90 (16.7%) | 10.4–25.7% |

- D vs C paired McNemar: 12 D-only successes, 0 C-only, exact p = 0.000488.
  This is **dev-replay**, not blind; the p-value is not a generalization claim.
- D funnel: `not_retrieved` 69, `not_extracted` 6, success 15, `not_in_answer` 0.
- Withheld claims across the 1,275-claim corpus: 872 → 203 after measure
  identity (different-measure-only conflicts 351 → 23; same-string measure
  conflicts 521 → 180). The remaining 203 are residual same-measure grouping /
  fragment cases and are not claimed to be false.
- By mode after the change:
  - snapshot: 128 SUPPORTED, 4 NEEDS_REVIEW, 1 INSUFFICIENT; D E2E 12/30.
  - rise-fall: 15 NOT_COMPARABLE (temporal/period), D E2E 3/30.
  - long-history: 5 SUPPORTED, 12 INSUFFICIENT; D E2E 0/30 because retrieval is
    0/30.

## Q4 ablations (same dev inputs and GT)

| Ablation | Result | Interpretation |
| --- | --- | --- |
| No evidence graph (C legacy) | E2E 3/90 | baseline |
| No verifier (all extracted claims in answer) | 16 GT answered, but 655 unsupported statements included | verifier removes 655 unsupported statements without losing GT answer coverage on dev; not proof of zero false support |
| No gap research | NOT_IMPLEMENTED | D retrieval is fixed to archived docs; no gap loop was run |
| BM25 only vs BM25+adaptive | tied in all 3 modes (0.1944 / 0.2167 / 0.4167 top-3 metric recall); 2 documents per archive | inconclusive; no measured lift |
| Old vs improved conflict grouping | supported 2 → 15; E2E 2/90 → 15/90 | main dev driver |

Retrieval remains the dominant limit: 69/90 GT facts are absent from C's own
archived documents, so no conflict/answer change can recover them. This requires
temporal/gap query planning and live retrieval, which is blocked on a paid
search/LLM cost gate (or a free retrieval source).

## Blind pilot (2 disjoint tasks / 10 facts)

| Group | Facts available | Answered | E2E |
| --- | ---: | ---: | ---: |
| A 安吉 | 4 | 0 | — |
| B 安吉 | 4 | 0 | — |
| C | NOT_RUN (smoke runs FAILED, no report) | — | — |
| D 安吉 + 信丰 | 10 | 4 | 4/10 (40%) |

D supported 5/10 facts; 4 were answered and supported. The pilot is too small
for a generalization claim; A/B have reports only for 安吉, C has no report, and
no paid live run was made. 信丰 A/B/C are NOT_RUN.

## Honest status

- Q3 implemented and evidenced on dev; Q4 has dev A/B/C/D plus one ablation and
  a 2-task blind pilot.
- The 40–60 task blind target is not met (2 tasks). See `docs/goal/DATASET.md`.
- No claim that D beats baselines on a representative sample; the dev effect is
  large but retrieval-limited, and the blind pilot is tiny.
- Remaining verifier withholding (203) needs a labelled audit before any
  “false rejection” rate is reported.
