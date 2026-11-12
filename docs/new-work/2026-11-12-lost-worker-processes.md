# A killed worker's processes are stopped, found by the job's id (#307, gap 3)

## What changed
A worker that was killed was reported `failed` with `WORKER_LOST` one lease later, and what it had
started ran on: with the real engine, a Godot, a virtual display and its wrapper, until their own time
limits.

Stopping them by the worker's process group number would be wrong: once the group is empty the system
can give that number to something else. So every worker's environment now names its job
(`EXPECTRAIL_JOB`, the job's random id), everything it starts inherits that, and the harness passes
that one name through to the game, the display and the sandbox tool. When a job is declared lost, the
store stops every process whose starting environment names the job (ask, then make) and the job's
reasons say how many. `cancel` does the same after stopping the group, which also catches a child
that started a session of its own. Where there is no `/proc` (macOS), nothing is stopped and the job
says so.

The name passed through is not a secret: it is the job's id, which is in the job's own folder name.

## What was run
- `python3 -m unittest tests.test_orchestrator`: 83 tests, OK. The seven new ones use real processes:
  kill only the worker, with a child in its group and one that left it; `wait` on a killed worker;
  cancel with a detached child; six bystanders (no id, another job's id, an id one character longer
  or shorter, the id inside another variable, a variable whose name only ends the same) that must
  survive; no `/proc`. Run against the code before this change, all seven fail.
- With real Godot 4.7.2, locally, not sandboxed: a verification started, its worker killed alone.
  Before the lease ran out Godot, Xvfb and the wrapper were still running; after it the job was
  `failed`, `WORKER_LOST`, "stopped 3 process(es) it had started", and none of the job's processes
  were left.
- The full suite: 1,989 tests, OK, 17 skipped.
- Not run: the same with the replay sandboxed (this machine has no bubblewrap). There the sandbox tool
  carries the id and the game inside dies with it; CI's sample step runs sandboxed but kills no worker.

## Not done
- Gap 7 of #307 (files changing between the worker's second read and the gate's copy): waits for #303.

## Files
`expectrail/orchestrator/store.py`, `expectrail/orchestrator/runner.py`, `harness/run.py`,
`harness/sandbox.py`, `tests/test_orchestrator.py`, `tests/orchestrator_worker.py`,
`docs/orchestrator.md`, `docs/capabilities.json`, `docs/capabilities.md`
