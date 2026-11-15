# Per-job budget and recorded phase costs (#267)

## What changed
Verification jobs now carry the `expectrail.job-budget/v1` object built by
`spend.build_job_budget`. It is in status.json and in job-budget.json beside the
other job files, including when no verification evidence can be published.
`expectrail status JOB --json` includes it; `expectrail report JOB` names caps,
recorded holds per phase, request counts, stops and the budget file. Holds are
explicitly not a provider bill. Older status records remain readable.

The worker snapshots at entry, phase changes, heartbeats and completion. Normal
jobs run in separate processes; the job-local adapter subtracts entry counters
so sequential offline stand-ins do not inherit earlier costs. It never resets
or raises a send cap. Snapshots and final decisions are serialized so a stale
heartbeat cannot clear a stop. Once observed, a stop remains with the job.
A raised BudgetStop or a stop recorded by the spend meter makes the completed
job needs-review with BUDGET_STOP; it cannot be accept. Cancellation and lost
workers keep their existing final state and last available cost snapshot.
Budget files never count as verification evidence.

Sean authorized editing only `build_job_budget` in spend.py after the initial
API blocker. Invalid caps now produce null plus a short reason naming the
variable, never its raw value. Recorded costs are retained, and all sender
functions remain unchanged. The builder uses the existing standard-library
schema validator so budget recording works in the installed wheel without
optional jsonschema. The request format and request.py did not change.

The verify-job schema references the existing budget schema; the runtime resolves
that one repository-owned reference locally. A new example includes phase costs
and an invalid-cap stop. The budget schema clarifies the meaning of null caps.

## What was run
Base main: a81861f5a5bbaae878680eb092be1edca77a6839, matching Sean's published
chatgpt/267-run-record-cost branch. The required historical fetch and read-only
main/branch fetch completed. No source from the #284 worktree was carried over.

Baseline full suite: 3,721 tests in 389.077s, OK (42 skipped), zero failures/errors.
Final focused run: 53 tests in 2.942s, OK. The 17 new tests cover retained costs,
malformed caps and safe reasons, sending still refusing, public CLI JSON and text
reports, budget stops (raised and swallowed), sticky stops, per-job counters,
active snapshots, cancellation, missing evidence, schema/reader validation,
worker ledger identity, and a worker with optional packages absent (`python -S`).
No real model call is made: holds and replay engines are offline stand-ins.

An intermediate integration run found four invalid-cap subcases that needed the
existing engine replay preserved, and the exact job-folder list needed its new
budget file. The replay behavior was preserved. The folder assertion was updated
and strengthened with a budget/job identity assertion. No existing test was
skipped or weakened. One after run was interrupted to include the snapshot lock
and sticky-stop regression; its separate log is not a full-suite result.
A complete after attempt ran out of disk space in synthetic replay fixtures:
97 errors, zero assertion failures, 42 skips. Its log and failure-name comparison
are retained separately. Removing 65 completed FakeGame discovery roots reclaimed
191,959,040 bytes; no product or test change was made for this environment failure.
Final full suite: 3,738 tests in 361.639s, OK (skipped=42).
Zero failures and errors before and after; failing test names on both runs: none.
No new failures. Full logs and the name comparison are in the handover.

## Not done
No live model, spend, hosted CI or new real-engine measurement. No bill
reconciliation: these are the spend API's recorded reservations. Abruptly killed
workers may have holds after their last snapshot; reports label interrupted
snapshots accordingly. Subsequent auto-fix work has its own repair record and
is outside this verification budget; child verifications have their own jobs.
Concurrent model jobs require separate worker processes, as the launcher uses.

No edits to any other spend.py function, gate/verify.py, top-level cli.py,
.github/, approved checks or bundled games. No commit, push, comment or PR.
The handover includes exact spend.py diff lines and the overlap sites with #284.

## Files
- contracts/job-budget.v1.schema.json
- contracts/verify-job.v1.schema.json
- contracts/examples/verify-job-budget.json
- expectrail/spend.py (build_job_budget only)
- expectrail/orchestrator/budget.py
- expectrail/orchestrator/runner.py
- expectrail/orchestrator/store.py
- expectrail/orchestrator/cli.py
- tests/test_job_budget.py
- tests/test_orchestrator.py (exact directory list and budget/job binding)
- docs/new-work/2026-11-15-run-record-cost.md
