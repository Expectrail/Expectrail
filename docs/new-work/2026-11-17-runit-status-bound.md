# Bound status answers and exercise the actual Worker on workerd (#265)

## What changed

Status answers wait at most 250 ms for freshness, then serve the last saved state
and its existing timestamp. One coalesced background refresh per request id shares
a two-second deadline across run-list/run/jobs/published-phase fetches and JSON
bodies. Timed-out attempts are cached for ten seconds. The Durable Object keeps
the task alive with `waitUntil`. Network reads no longer occupy the admission lock;
state commits remain serialized and reject stale/pruned observations. Confirmed
run ids survive later read failures. The smoke's status timeout is five seconds,
clipped to its remaining overall wait.

An unreadable observation cannot manufacture a failure, increment/reset the
breaker or release the active reservation, including past the thirty-minute
tracking age. Successful observations still enforce existing tracking policies;
confirmed workflow failures still count. Busy now describes a reservation or run.
No response schema or verdict policy changed.

The optional npm lane pins Miniflare 4.20260730.0 and workerd 1.20260730.1 with a
complete lock. It runs the actual Worker, SQLite Durable Object and service on
Cloudflare's native runtime, with allowlisted fake GitHub and fixture strings only.
Miniflare metadata fetching is disabled; host HTTP rejects non-loopback destinations.
It checks healthy phases, concurrent slow polls, body deadlines, redirects and a
mutation back to the runtime-incompatible redirect option. The latter is paired
with a real Node fetch over loopback, demonstrating why Node alone missed #595.
Missing runtime skips by name; required mode fails; discovery never installs it.
The proposed hosted job is text for Sean, with no workflow edit.

The Run it ledger/README/site text now cites Sean's recorded November 17 visitor
runs instead of saying undeployed. GitHub verify/publish job success was read back
for runs 44133603903, 44135389301 and 44135877669; their recorded source is bf31c92
and deployed version 93567b5a. This patch has not been deployed. Receipts remain unsigned.

Guard: test change intended (#265)

The existing thirty-minute test keeps its final failed-state assertion after a
successful observation. It additionally asserts that unreadable status past that
age retains the reservation and breaker count. Its previous failure-on-read-error
expectation contradicted this task's honest status rule. No assertion was deleted
or threshold loosened; the other service and response-contract assertions remain.

## What was run

Base: `49226b6cdadda80754ecee1c61ed33116aeb9b6c`, latest main at task start, on
`chatgpt/265-status-bound`. AGENTS.md read first; required historic
`c169a5e0da304773587304ed47bc8aabcec80da7` fetch completed. No source edits before
the full baseline finished. Existing prior handover worktrees were preserved.

- Full before, all `EXPECTRAIL_*` variables unset: **4,700 tests, 1053.600s,
  four failures, 60 skips**. These all predate this change:

  | Failure | Observed cause and limit of investigation |
  | --- | --- |
  | `tests.test_orchestrator.LostWorkerTest.test_cancel_also_stops_what_left_the_workers_group` | Ten-second engine-ready wait expired. Passed on focused repeat; the baseline startup cause is not established. |
  | `tests.test_orchestrator.LostWorkerTest.test_killing_only_the_worker_leaves_nothing_of_the_job_running` (`engine='slow'`) | Same ten-second wait. Passed on repeat; root cause not established. |
  | Same method (`engine='detached'`) | Same wait; passed on repeat. |
  | `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once` | 0.8136s against 0.5s. Reproduced at 0.9326s. A diagnostic measured 1.3409s of real cleanup inside 1.3468s total, including three process scans. This is the unmerged #365 test distinction in the preceding #249 handover, not a Worker change. |

- Before product changes, six new Node cases: **five failures, one pass** on main,
  recorded. Failures cover blocked status, body/published-phase waits, dispatch-lock
  queuing and false age-based failure. Then **31/31 service tests passed**, 6.587s.
  Smoke timeout tests first failed on ten versus five seconds; **16/16 passed**
  afterward, 1.520s. Existing Worker/smoke focus: **27 tests, 10.548s, OK**.
- Direct workerd probe reproduced `redirect: "error"` being rejected before fake
  GitHub received a request. Initial native behavioral run: **5/5**, 77.184s.
  That early run did not disable possible SDK metadata fetching and is not cited
  as zero-network evidence. Initial required Python wrapper: **4 tests, 84.226s,
  OK**, including merged response-reader validation.
- During egress-guard development, one 30-poll batch exceeded its unchanged
  1.2-second test envelope. The guard was changed to delegate to the SDK's existing
  dispatcher rather than replace its pools; targeted repeat passed in 24.474s.
  The single timing outlier's cause is not established. All bounds are retained.
- Final direct native lane: **5/5, 67.775s, zero skips**; host non-loopback HTTP
  attempts **zero**. The 30-answer batch completed in **382.98 ms** in the final log. All **46** saved native bodies pass the merged API reader. The same
  healthy/timeout/coalescing/redirect/negative-control assertions all ran.
- Fresh `npm ci --ignore-scripts --no-audit --no-fund` from the delivered lock
  succeeded in the external runtime directory. Initial npm cache configuration
  attempts failed; an explicit task-local cache and empty user/global config
  resolved them. No credential was read or written.
- Missing-runtime controls: a named local skip; required mode returns nonzero with
  `EXPECTRAIL_WORKER_TESTS=required`, as intended. Four tests load with numpy/PIL
  blocked; three core tests also pass with both blocked (6.769s).
- CI proposal YAML and every Bash step parse; contents-read only, no environment.
  Its editable install with only the contracts extra succeeded in a fresh venv;
  three core checks passed there in 6.585s. Capability render/check passes.
  **Full after: 4,704 tests, 890.685s; FAILED (failures=1, skipped=60). Remaining failures match the unmodified baseline; no orchestrator test or implementation is changed here.**
- **Public export: 844 files, 13 prohibited paths excluded by metadata before opening, zero errors/warnings. Patch/log export, base application and zip CRC verified.**

Full logs retain every baseline/development failure and its name/cause, with the
intentional red tests and prerequisite negative control labelled separately.

## Not done

No deployment, deployed API call, real dispatch, model call/spend, account/key,
GitHub write, push or PR. No workflow, approval, game source or protected verifier/
orchestrator implementation changed; no private/blind/fresh content read.

The native lane uses compatibility date 2026-07-30, matching its pinned engine.
The production example's later 2026-11-01 compatibility set and the deployed engine
version are not validated. No hosted CI run of the proposed job. No new game
verification or signed receipt. No closure of #265 is claimed.

The existing orchestrator timing test was not changed here; its #365 fix is in
the prior #249 handover. Baseline startup failures were not root-caused. Reviews
on #599 and #603 are handled as the separate Task 2; no wheel/sample or site-offline
review fix is included in this status-bound patch.

## Files

- `apps/run-it-edge/service.js`, `worker.js`, `package.json`
- `apps/run-it-edge/runtime/package.json`, `package-lock.json`
- `apps/run-it-edge/test/service.test.mjs`, `status.test.mjs`, `runtime-check.mjs`, `runtime.test.mjs`
- `tools/runit_api_smoke.py`, `tests/test_runit_status_bound.py`
- `README.md`, `docs/index.html`, `docs/capabilities.json`, `docs/capabilities.md`
- `docs/run-it.md`, `docs/run-it-deploy.md`, `docs/run-it-status-bound.md`
- `docs/proposals/265-workerd-runtime.yml.txt`, this work log
