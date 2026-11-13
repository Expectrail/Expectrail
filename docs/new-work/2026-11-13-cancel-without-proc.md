# Cancel and lost-worker cleanup without /proc (#378)

## What changed

Added a macOS process-discovery path using `ps -E -ww`, restricted to the caller's real uid
with `-U`. A second read without `-E` separates command arguments from the environment, so a
job marker in argv is not treated as an environment assignment. The parser also checks the
returned uid, excludes zombies, and follows parent ids to exclude the caller and its ancestors.
All ps output stays in memory; errors never include its environment or stderr.

Without /proc, cancellation signals only individually rechecked job markers. It does not trust
the stored process-group number, which can be stale or refer to an unsignalable group, and it
can still find detached or reparented same-user children after the worker dies. If ps is missing,
refuses access, is malformed, or cannot confirm a process's identity, the job says cleanup could
not be confirmed. A process that loses its marker is not signalled, but is not counted as stopped
while ps still shows it alive. Absence from the same-user table is followed by a signal-0
existence check, so changing uid cannot be misreported as exit. TERM is followed by KILL and later children are counted too.

Linux's /proc discovery, pidfd signalling and ordinary group/marker cleanup are retained.
Group permission failures are now caught after cancellation is recorded; the job states that the
group could not be stopped, still attempts marker cleanup, and its command keeps exit code 4.
The group stop distinguishes a group that has gone from permission denied for an existing group,
and reports a permission failure while waiting rather than assuming exit.

## What was run

- Required first fetch: `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`.
- Main base: `b37bd3e0b8d35eb9c4befe7b602511d39263b5e8` (PR #389). Read AGENTS.md before changes.
- Before and after: `python3 -m unittest discover -s tests -t .`, on separate worktrees of the
  same main commit. Before: 2,911 tests, 2 failures, 2 errors, 31 skipped, 757.310 s.
  After: 2,929 tests, 2 failures, 2 errors, 31 skipped, 666.797 s. Compared failing test names
  AND failure/error types: identical, no new or removed failures. Both raw logs are in the handover.
  The existing environment failures are:
- ERROR: `setUpClass (tests.test_event_input.EventInputTest)`
- ERROR: `test_a_real_fix_is_accepted_with_the_private_sessions_mounted (tests.test_web.FixLoopTest.test_a_real_fix_is_accepted_with_the_private_sessions_mounted)`
- FAIL: `test_a_bug_its_checks_cannot_see_is_not_detected_without_sam (tests.test_web.FixLoopTest.test_a_bug_its_checks_cannot_see_is_not_detected_without_sam)`
- FAIL: `test_without_the_private_sessions_nothing_is_accepted (tests.test_web.FixLoopTest.test_without_the_private_sessions_nothing_is_accepted)`
- An earlier post-change full run was interrupted to add the signal-0 exit confirmation. Its
  separate log is included, but only the completed final run is used in the comparison.
- `python3 -m unittest tests.test_orchestrator`: 103 tests, OK; existing tests untouched.
- `python3 -m unittest tests.test_cancel_without_proc`: 18 tests, OK. Tests patch the /proc
  existence check and supply separate ps command/environment outputs; they do not call native
  macOS. Cases cover same-user selection, exact markers, argv, ancestors, zombies, detached
  children, disappearing markers, TERM/KILL, ps failures, denied process/group signals, and
  uid changes, and the cancel command's exit code 4.
- `git diff --check`: passed.

## Not done

Native macOS was not run. The exact cause of Sean's original killpg PermissionError was not
reproduced on his Mac; the gone-group and permission-denied cases are covered with stand-ins.
The ps view is the environment the OS exposes, not proof against a process deliberately
concealing or forging its own job marker. Without a readable same-user ps inspection, cleanup
is reported as unconfirmed; no process-group-number guess replaces it.

No changes to the other #378 groups, app files, .github/, either game tree, or spec approvals.
No held-out or fresh paths opened, no paid model calls, and no GitHub writes, commits or pushes.
The architect session validates the handover on Linux and pushes it.

## Files

- `expectrail/orchestrator/store.py`
- `tests/test_cancel_without_proc.py` (new; no existing test changed)
- `docs/new-work/2026-11-13-cancel-without-proc.md`

## Architect run (Linux)
On main 4675f9d: before 3014 tests OK (27 skipped); after 3032 tests OK (27 skipped). `tests.test_cancel_without_proc` 18 OK, `tests.test_orchestrator` 103 OK. Not run on macOS.
