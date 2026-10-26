# Q6 — Final Acceptance

Updated: 2026-10-26 · branch `codex/quality-recovery`
No paid Provider or semantic Judge calls.

## Engineering verification (all executed locally)

| Check | Result | Evidence |
| --- | --- | --- |
| Python suite | **692 passed**, 1 Starlette deprecation warning | `.venv\Scripts\python.exe -m pytest --no-cov -q` |
| Ruff `src tests` + new scripts | clean | `ruff check src tests scripts/...` |
| Frontend typecheck | clean | `cd web; npm run typecheck` |
| Frontend unit tests | 4 passed | `cd web; npm test` |
| Frontend build | 160.97 kB JS | `cd web; npm run build` |
| Browser E2E | **2 passed in 14.9 s** | `cd web; npm run test:e2e`; traces/screenshots in `experiments/quality/20261026_q5_e2e/` |
| Legacy CLI | exit 0 | `python -m county_research_ai.cli --county 安吉县 --dry-run` |
| M0–M4 regression | no failing tests; CLI and all three modes retained | suite + CLI smoke |

## Research findings

- Q1 attribution: retrieval is the dominant bottleneck (21/90 GT facts in C's
  archived docs; long-history 0/30). Coarse/decontextualized claim identity caused
  872 withheld claims.
- Q3 measure identity + period inference + verified extractive answer:
  - withheld claims 872 → 203;
  - GT-supported facts 2 → 15;
  - dev E2E 3/90 (C) → 15/90 (D), paired McNemar 12 vs 0, p=0.000488 (dev only).
- Q4 ablations: no-verifier matched 16 GT answers but included 655 unsupported
  statements; BM25 vs adaptive tied; old grouping supported 2 vs new 15.
- Blind pilot (2 tasks / 10 facts): D 4/10 E2E, 5 supported; A/B 0/4 on 安吉;
  C NOT_RUN (smoke runs FAILED). Too small for generalization.
- Retrieval remains capped by the archived corpus; gap research and live
  retrieval were not run.

## Acceptance against the stated conditions

| Condition | Status | Note |
| --- | --- | --- |
| Traceable four-stage quality attribution | PASS | Q1 funnel + withheld review |
| Strategy D implemented with real data | PASS (dev + pilot) | not a representative quality claim |
| Dataset with sources/labels/hashes; dev/blind isolation | PARTIAL | 2 blind tasks; 40–60 target not met |
| A/B/C/D + key ablations reproducible | PARTIAL | dev + 2-task blind; no live; no-gap NOT_RUN |
| Verifier false rejection/support independently assessed | PARTIAL | 12 pre-fix exact-evidence candidates; 0 supported-by-metric-only in sample; no labelled false-support rate |
| All local runnable tests pass | PASS | 692 Python + 4 frontend + 2 E2E |
| M0–M4 no regression | PASS | suite + CLI dry-run |
| Improvement significance stated honestly | PASS | dev effect only; blind tiny; no generalization |

## Statistical statement

- Dev-replay D vs C E2E: 15/90 vs 3/90; Wilson 95% CI 10.4–25.7% vs 1.1–9.3%;
  McNemar exact p=0.000488. This is a **dev** result after tuning and does not
  establish blind or live generalization.
- Blind pilot: D 4/10 (Wilson ~16.8–68.7%); A/B 0/4; C NOT_RUN. No significance
  claim.
- No token/cost superiority is claimed.

## Remaining work / blockers

1. Curate 38–58 additional independent blind tasks with verified quotes/hashes.
2. Run a budgeted live end-to-end evaluation and a semantic Judge; currently
   `BLOCKED_EXTERNAL` (no cost authorization).
3. Implement and measure gap-driven retrieval and temporal query planning; this
   is required to move beyond the 69/90 retrieval gap.
4. Two-process live lease stress test; current lease invariants are store-tested.
5. Labelled false-support audit; current sample is unlabelled.
6. Human rubric adjudication and CI browser setup.

## Verdict

Engineering acceptance for the scoped local system: **PASS**.
Research acceptance: **PARTIAL** — the dev improvement is real and reproducible,
but the blind sample is 2 tasks, live evaluation is blocked, and retrieval
coverage remains the dominant unresolved bottleneck. The project does not claim
that Strategy D beats the baselines on a representative sample.
