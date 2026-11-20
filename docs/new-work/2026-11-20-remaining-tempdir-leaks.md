# The last three test temporary-folder leaks (follow-up to #681)

## What changed

#681 fixed the big one, `tests/jit_fixtures.Case`, which had left 12,890 folders. Its work log named
three smaller leaks, a few hundred each. All three are fixed here.

- **`tests/submission_commit.extract`** returns a folder of files from a fixed commit. Its callers hold
  it for a test and have no cleanup hook of their own, so every call leaked one. It now registers the
  folder and an `atexit` hook removes them, so a suite run leaves nothing behind.
- **`tools/runit_smoke.smoke`** made two folders, the results directory and the stub root, and removed
  neither. The decision about what it may remove is now its own function, `folders_to_remove`: only
  folders this run made, and only on a clean finish. A run with problems, or one that leaves by an
  exception, keeps everything and names it in the log and in the returned document under `kept`.
- **`tests/test_runit_smoke.InChromium.smoke`** removes whatever a run kept. One of its tests fails the
  smoke on purpose, so without this the suite would still leak two folders per run.

Nothing a person running `python3 -m tools.runit_smoke` wants is lost: `--json` and `--screenshots`
write to paths the person names, and a failing run keeps everything.

## The merge guard's two findings on the first attempt, and what changed

My first attempt removed both folders whenever `problems` was empty. The guard found that this
**deletes the repository checkout** on a clean real run: `root` comes from the runner factory, and
`runit_stub.real_runner` returns `ROOT`, the repository itself. Only `stand_in_runner` makes a
temporary root. Every test used `stand_in=True`, so no test saw it. The guard proved it with a probe
that recorded the `rmtree` calls.

Its second finding: if the `try` left by an exception, `problems` could still be empty and both
folders went anyway, which contradicted "a failing run keeps everything".

The fix ends the class rather than patching the case. The runner factories now say whether the caller
owns the root (`real_runner` returns `False`, `stand_in_runner` returns `True`), and nothing hands a
path to `rmtree` that it did not make. A `finished` flag, set only on the normal path, keeps the
folders when an exception leaves the run.

`folders_to_remove` exists so the decision can be tested without a browser. My first test attempt
could not fail on the broken code, because mocking the runner factory changed its return arity and the
old code raised before reaching the cleanup; a test that cannot fail proves nothing. Substituting the
old decision into the new tests fails 2 of 4, naming the repository deletion and the exception case.

## What was run

- `tests.test_discovery_freeze` and `tests.test_mutation_registration`: OK, and
  `expectrail-submission-*` afterwards: **0** (it was one per call before).
- `tests.test_runit_smoke`: OK, including four new `CleanupOwnership` tests. With the previous
  decision substituted, 2 of those 4 fail: the default-mode run removing the repository, and an
  interrupted run removing anything. And `expectrail-smoke-results-*` plus
  `expectrail-stub-root-*` afterwards: **0** (two per run before, including from the
  deliberately-failing test).
- The full suite in 3 parts, and the export scan.

## Not done

- No other prefix in the system temporary directory leaks after #681 and this change, by inspection of
  a full run. If a new fixture adds one, the pattern to copy is here or in #681.

## Files

- `tests/submission_commit.py`
- `tools/runit_smoke.py`
- `tools/runit_stub.py`
- `tests/test_runit_smoke.py`
- `docs/new-work/2026-11-20-remaining-tempdir-leaks.md`
