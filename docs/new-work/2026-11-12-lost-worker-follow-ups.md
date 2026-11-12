# Stopping a lost job's processes: the gaps from the review of #314 (#307)

## What changed
The merge guard merged #314 and listed five gaps, none worse than before it (when nothing was stopped).

- **The signal goes to a handle, not a number.** Between looking at a process and signalling it, its
  number could pass to another program. Each process is now held by a handle (`pidfd`), its environment
  is read again through that hold, and the signal is sent to the handle. Nothing is signalled by number.
- **The caller and its ancestors are never stopped.** A status or a cancel asked from a script running
  inside the job stopped the script's own shell.
- **The count is what is confirmed gone.** The job's reasons said "stopped N" for the number found. They
  now say how many were found and how many are gone, and say so when some are still running.
- **What the docs claimed.** The environment read is what a process holds now, not what it started with:
  a program that writes over its own environment is not found. `docs/orchestrator.md` says so, and that
  the sandboxed game cannot stay alive that way.
- **A run with the replay sandboxed.** A test for the real tool and the real engine: a verification of
  the bundled game in the `isolated` class, its worker killed alone while bubblewrap is running the
  replay. It runs in CI's `seeded-bugs` job, where the tests that need bubblewrap are required. Its
  first run corrected what I expected: I had the sandbox outliving the worker until the store stopped
  it, as an unsandboxed game does. With real bubblewrap nothing of the job was left the moment the
  worker died, because the tool is started with `--die-with-parent` and the kernel kills it with the
  worker. The test now holds that: nothing left without anyone being asked, then `failed` with
  `WORKER_LOST`.

## What was run
- `python3 -m unittest tests.test_orchestrator`: OK; ten tests on lost workers, all with real processes.
- The full suite: 1,993 tests, OK, 18 skipped (8 need bubblewrap).
- Not run locally: the sandboxed test (this machine has no bubblewrap). Its runs are this pull
  request's `seeded-bugs` jobs; the pull request reports them.

## Not done
- Finding a process that has written over its own environment (unsandboxed only). Stated as a limit.
- Gap 7 of #307, which waits for #303.

## Files
`expectrail/orchestrator/store.py`, `tests/test_orchestrator.py`, `tests/test_replay_sandbox.py`,
`docs/orchestrator.md`
