# Any failure of the process-handle path falls back to the process number (#307)

## What changed

#316 was merged at 04:43:00 UTC on November 12. The merge guard's second review of it, posted at
04:43:57, says "not merged" and gives one more regression: `_exited` asked whether a handle's process had exited with `select.select`, which refuses
a descriptor numbered 1024 or higher. A caller holding that many open files gets such a handle, the
call raised, `lose` and `cancel` raised with it, and the lost job's processes ran on. Before handles
they were stopped. So main carried a regression from 04:43 UTC until this change.

It is the same mistake twice. In #316's first round I kept the old way only for "no handle can be
had"; the guard's point is that the old way must cover every failure of the new one.

- `_exited` asks with `select.poll`, which takes a descriptor of any number.
- The whole handle path (open, read the environment again, liveness check, signal) is one function,
  `_by_handle`, and `_signal` has one fallback for it: whatever step fails, and however, the
  environment is read again and the signal goes to the number if it still names the job. Only "no
  such process" ends it. A third way for the handle to fail cannot leave the processes running.
- The job's reasons say "by process number" and why: "this system has no process handles" or "a
  process handle could not be used". They are told how the signals were actually sent, instead of
  asking the system afterwards whether handles exist.
- An error in the stop itself is not raised past `lose` or `cancel`: the job is already final, so it
  becomes a reason on the job ("could not stop what it had started: ...").
- A process the job starts after the first look is found by a later look and is in both counts.
  Before, it was signalled and counted in neither, so "stopped N" could be said with one more running.

## What was run

- `python3 -m unittest tests.test_orchestrator.LostWorkerTest`: 19 tests, OK, real processes.
- The same new tests against main's `store.py` (b76d90c): the high-numbered-handle test raises
  `ValueError: filedescriptor out of range in select()`, the guard's finding; a failing liveness check
  and an `EINVAL` from the signal raise; an `EPERM` from the signal leaves the process running.
- The full suite: 2,032 tests, OK, 22 skipped (bubblewrap and Unity, as on main).
- Not run: an old kernel or a container that really lacks `pidfd_open`. Those are stood in for by
  patching the call to raise, as in the guard's own runs.

## Not done

- A process that writes over its own environment is still not found (unsandboxed only; stated in
  `docs/orchestrator.md`).
- #307's other open pieces: the import cache's key against what its copy held (found in the review of
  #318), and the specs and routes read twice.

## Files

`expectrail/orchestrator/store.py`, `tests/test_orchestrator.py`, `docs/orchestrator.md`
