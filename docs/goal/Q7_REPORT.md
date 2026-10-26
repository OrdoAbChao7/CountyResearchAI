# Q7 — Retrieval Recovery & Generalization Validation

Updated: 2026-10-26 · branch `codex/quality-recovery`
No paid Provider or Judge calls. All new retrieval used free public pages.

## Q7.1 Retrieval recovery

### Archived corpus pool

All `experiments/**/raw_docs.json` were pooled per region and deduped by
URL/content hash. The pool contains 8 regional corpora (including the Anji and
Xinfeng smoke runs); exact sizes are recorded in
`experiments/quality/20261026_q7_pooled_eval/summary.json`.

| Condition | Retrieved | D supported | D answered | D E2E |
| --- | ---: | ---: | ---: | ---: |
| C own archived docs (Q3) | 21/90 | 2 | 2 | 3/90 (3.3%) |
| D archived (Q3) | 21/90 | 15 | 16 | 15/90 (16.7%) |
| D pooled archive | 47/90 | 35 | 35 | **33/90 (36.7%)** |
| D pooled + free-web hits | 52/90 | 36 | 33 | 31/90 (34.4%) |

By mode, D pooled archive: snapshot **29/30 retrieved, 25/30 E2E**;
rise-fall **18/30 retrieved, 8/30 E2E**; long-history **0/30 E2E**.

The pooled archive recovers **26 of the 69** C-missing facts (69 → 43 missing).
It does **not** recover long-history (0/30): the facts are historical and absent
from every archived run.

### Free public web (DuckDuckGo HTML + direct fetch)

Bounded, cached, no paid API. Queries use region/metric/year and document-type
variants, not the GT URL. Results:

| Set | Facts | Recovered | Exact excerpt | Value+metric | Requests | Time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| long-history | 30 | **6 (20.0%)** | 4 | 2 | 121 | 654.7 s |
| rise-fall missing | 12 | 0 | 0 | 0 | 44 | 228.6 s |
| Oracle GT-URL fetch (diagnostic only) | 30 | **17 (56.7%)** | 16 | 1 | 18 | 101.1 s |

The oracle probe uses the GT URL and is **not** Strategy D. It proves the source
availability ceiling: 17/30 long-history facts are still reachable and present
when the URL is known. Autonomous discovery recovers only 6/30, so the dominant
remaining failure is **discovery/query planning and page discovery**, not source
death. Only 1/6 autonomous hits was an official domain; the others were news or
secondary pages.

Total retrieval-level recovery: **32/69 (46.4%)** = 26 pooled-archive + 6
free-web long-history. Adding free-web docs to the pooled D corpus did **not**
raise E2E (31 vs 33); one snapshot task lost 2 facts through new-document
extraction/conflict effects. Retrieval recovery alone is not sufficient.

Defects found and fixed along the way:
- public-page charset detection (UTF-8 pages were mis-decoded as GBK);
- GT values were initially treated as years in the funnel;
- region/year constraints were not enforced in the first scoring pass;
- long-history source metadata (`政府工作报告`) was missing from the query plan.

## Q7.2 Verifier audit

Stratified sample of 25 claims from the 18 C runs: 10 SUPPORTED, 10
NEEDS_REVIEW, 5 INSUFFICIENT. The frame had no NOT_COMPARABLE/OUTDATED claims.
Labels are **assistant manual review**, not human ground truth; human annotation
is `BLOCKED_HUMAN_ANNOTATION`.

| Status | correct | incorrect |
| --- | ---: | ---: |
| SUPPORTED | 7 | 3 |
| NEEDS_REVIEW | 10 | 0 |
| INSUFFICIENT | 1 | 4 |

- **False support**: 3/10 = **30.0%** (Wilson 95% 10.8–60.3%).
- **False rejection**: 4/15 = **26.7%** (Wilson 95% 10.9–52.0%).
- Error types: period/metadata rejection 2; wrong span link rejection 2;
  fragment/wrong-measure support 1; period-mismatch support 1; sign/measure
  mismatch support 1.

Concrete errors:
- SUPPORTED `增长7.3%` accepted against electricity growth, not the claimed
  rural-income measure.
- SUPPORTED `下降3.5%` for budget revenue accepted from a social-security
  `-3.5%` sentence; budget revenue was `+3.5%`.
- SUPPORTED a 2026 article fact labelled period 2022.
- Rejected correct facts because the claim year was only in document metadata,
  or because the span link pointed to the wrong chunk.

These rates describe this small stratified sample, not the full population.

## Q7.3 Independent holdout

- `PILOT`: the two Anji/Xinfeng tasks, 10 exact-quote facts, remain PILOT and
  are not treated as final unseen evidence.
- `SEALED_HOLDOUT`: **0 tasks**. No new independent tasks were fabricated or
  relabelled. Target 40–60, achieved 2 pilot tasks; gap 38–58.
- Reason: only the two disjoint archived sources met the exact-quote/hash
  standard without new authorized retrieval/annotation. Free search can find
  pages, but building 40–60 verified tasks requires substantial new annotation
  and source curation.

Q7.3 is **NOT_MET**.

## Q7.4 Evaluation

Task-clustered bootstrap (18 task clusters, 4,000 resamples, dev replay only):

| Comparison | Task-level E2E difference | Bootstrap 95% | Wins / ties / losses |
| --- | ---: | --- | --- |
| D pooled − C | +0.333 | 0.156–0.522 | 9 / 9 / 0 |
| D archived − C | +0.133 | 0.022–0.278 | 5 / 13 / 0 |
| D pooled+free − C | +0.311 | 0.144–0.489 | 9 / 9 / 0 |
| D pooled − D archived | +0.200 | 0.067–0.367 | 6 / 12 / 0 |
| D pooled+free − D pooled | −0.022 | −0.067–0.000 | 0 / 17 / 1 |

Interpretation: on dev, corpus pooling is the strongest driver; free-web hits
add no measurable E2E on top. Long-history remains 0 E2E. These are dev-replay
results, not a sealed-holdout or live result.

Ablations: old vs measure-aware grouping (2 → 15 supported), no verifier (16 GT
answers but 655 unsupported statements included), BM25 vs adaptive tied. No-gap
retrieval is the negative result above. A/B were not re-run on the pooled corpus
because their archived outputs lack raw docs; the 2-task pilot has A/B only for
Anji (0/4) and C NOT_RUN.

## Q7.5 Reliability

Two independent spawned processes, 6 jobs, lease 0.45 s:
`experiments/quality/20261026_q7_stress/summary.json`.

- all jobs terminal; exactly one successful terminal write per job;
- lease-expiry takeover occurred, stale worker finish rejected;
- one worker crashed after claim; `recover_interrupted()` marked it and the
  recovery worker completed it;
- normal jobs had exactly one claim; run took 3.0 s.
- Existing Python/frontend/Playwright suites still pass.

## Q7.6 Answers

1. **How many of the 69 missing facts were recovered?** 32 at retrieval level:
   26 by pooling all archived runs, 6 by autonomous free-web long-history search.
   D E2E moved from 3/90 (C) to 33/90 (pooled) and 31/90 (pooled+free).
2. **Did long-history improve from 0/30?** Retrieval: yes, to 6/30 (20%);
   D E2E: no, still 0/30. Oracle source fetch finds 17/30, so discovery and
   extraction/answer integration remain the blockers.
3. **Does D beat A/B/C under the same conditions?** On the dev corpus, D pooled
   beats C with a task-clustered interval; A/B were not re-run on the pool, and
   the sealed holdout is absent. **No independent generalization claim.**
4. **Verifier false rejection/support rates?** Sample estimates 26.7% (4/15)
   false rejection and 30.0% (3/10) false support; assistant labels, wide CIs.
5. **Cost per additional correct fact?** No paid cost. Pooled recovery used
   existing archives (0 new requests). Free web: 121 requests / 655 s for 6
   long-history recoveries (~109 s and ~20 requests per recovered fact); oracle
   probe 18 requests / 101 s for 17 availability checks. These are wall-clock
   and request counts, not monetary cost.
6. **What holds only on dev vs independent?** All D/C improvements and bootstrap
   intervals are dev-replay. The 2-task pilot is too small for generalization.
   Nothing passes a sealed-holdout test because no sealed set was built.
7. **Remaining blockers:** 38–58 verified independent tasks; autonomous
   historical discovery; extraction/answer integration for recovered docs;
   human verifier labels; live Provider/Judge cost gate.

## Status

| Sub-phase | Status |
| --- | --- |
| Q7.1 retrieval recovery | PARTIAL — 32/69 recovered; long-history retrieval 6/30, E2E 0/30; oracle proves discovery gap |
| Q7.2 verifier audit | PARTIAL — 25 assistant labels; false support 30%, false rejection 26.7%; human labels blocked |
| Q7.3 independent holdout | NOT_MET — 2 PILOT tasks, 0 SEALED |
| Q7.4 evaluation | PARTIAL — dev cluster bootstrap; no sealed A/B/C/D |
| Q7.5 reliability | PASS — two-process stress and regressions |
| Q7.6 final acceptance | PARTIAL — engineering evidence strong; research generalization not established |
