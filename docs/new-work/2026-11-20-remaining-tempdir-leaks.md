# The last three test temporary-folder leaks (follow-up to #681)

## What changed

#681 fixed the big one, `tests/jit_fixtures.Case`, which had left 12,890 folders. Its work log named
three smaller leaks, a few hundred each. All three are fixed here.

- **`tests/submission_commit.extract`** returns a folder of files from a fixed commit. Its callers hold
  it for a test and have no cleanup hook of their own, so every call leaked one. It now registers the
  folder and an `atexit` hook removes them, so a suite run leaves nothing behind.
- **`tools/runit_smoke.smoke`** made two folders, the results directory and the stub root, and removed
  neither. A **clean** run now removes both. A run **with problems** keeps them, names them in the log
  and in the returned document under `kept`, because a failure is when someone wants to look.
- **`tests/test_runit_smoke.InChromium.smoke`** removes whatever a run kept. One of its tests fails the
  smoke on purpose, so without this the suite would still leak two folders per run.

Nothing a person running `python3 -m tools.runit_smoke` wants is lost: `--json` and `--screenshots`
write to paths the person names, and a failing run keeps everything.

## What was run

- `tests.test_discovery_freeze` and `tests.test_mutation_registration`: OK, and
  `expectrail-submission-*` afterwards: **0** (it was one per call before).
- `tests.test_runit_smoke`: 12 tests, OK, and `expectrail-smoke-results-*` plus
  `expectrail-stub-root-*` afterwards: **0** (two per run before, including from the
  deliberately-failing test).
- The full suite in 3 parts, and the export scan.

## Not done

- No other prefix in the system temporary directory leaks after #681 and this change, by inspection of
  a full run. If a new fixture adds one, the pattern to copy is here or in #681.

## Files

- `tests/submission_commit.py`
- `tools/runit_smoke.py`
- `tests/test_runit_smoke.py`
- `docs/new-work/2026-11-20-remaining-tempdir-leaks.md`
