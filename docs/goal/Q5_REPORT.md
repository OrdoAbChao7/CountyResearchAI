# Q5 — Engineering Reliability Report

Updated: 2026-10-26 · branch `codex/quality-recovery`
No paid Provider calls.

## Implemented

### SQLite execution leases + fencing

- `jobs` now carries `lease_owner`, `lease_expires_at`, `fencing_token`.
- `claim_for_execution(job_id, owner, lease_seconds)` is atomic and only wins
  for QUEUED/INTERRUPTED or an expired RUNNING lease.
- `renew_lease` is called by a daemon heartbeat every `lease/3` seconds.
- `finish_job` updates the terminal state and inserts the terminal event in one
  transaction, guarded by owner + fencing token.
- Startup `recover_interrupted` only rewrites RUNNING jobs with an empty/expired
  lease; live leases are preserved.
- Worker stops on lease loss and logs a stale result instead of writing it.

Tests:
- `test_live_lease_blocks_recovery_and_takeover`
- `test_expired_lease_takeover_rejects_stale_terminal_write`
- `test_concurrent_claims_have_exactly_one_winner`
- `test_claim_for_execution_is_atomic`

### Per-job storage isolation

API jobs now write under `<data>/api_jobs/<job_id>/` and
`<reports>/api_jobs/<job_id>/`. Concurrent jobs with the same county/focus/date
cannot overwrite each other. Test:
`test_jobs_do_not_overwrite_each_others_reports`.

### Browser E2E (Playwright 1.64.1 + Chromium)

`web/tests/e2e/workspace.spec.ts`:
1. create a task from the form, observe the SSE timeline (`job.completed`,
   `evidence.persisted`), open the 证据 tab, expand a finding, open the source
   viewer and assert the quote is highlighted, then download the brief.
2. create via API, cancel the running task, assert `已取消`, click 恢复运行,
   assert `运行中` then `已完成`.

Result: **2 passed in 15.0 s** (`npm run test:e2e`). Artifacts:
`experiments/quality/20261026_q5_e2e/playwright.log`,
`screenshots evidence.png / brief.png / cancel-resume.png`, and
`trace-1.zip` / `trace-2.zip`.

The deterministic cancellation uses
`AXIOMSCOPE_MOCK_STAGE_DELAY_SECONDS=3` (MOCK only, max 10 s). It is not a LIVE
backdoor and does not affect production runs.

## Fault injection / concurrency

- stale fenced terminal write rejected;
- expired lease takeover increments the token;
- concurrent claims: exactly one winner;
- live lease not recovered;
- concurrent jobs use distinct report files.

## Not run / limits

| Item | Status |
| --- | --- |
| Two real uvicorn processes stress test | NOT_RUN (store invariants tested, not a multi-node run) |
| Cancel inside a single long provider call | NOT_SUPPORTED (stage boundaries only) |
| Clock skew / distributed lease clock | NOT_TESTED |
| Authentication / authorization | NOT_IMPLEMENTED (localhost MVP) |
| Browser test in CI without Chromium download | NOT_RUN |

Q5 is **PASS for the implemented local reliability scope**; multi-process live
stress remains NOT_RUN and is not claimed.
