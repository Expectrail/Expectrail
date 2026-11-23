# Keep the late-process test independent of the host PID table (#378)

## What changed

The late-process cleanup test supplies a final process table and a liveness probe for its fictional PIDs. The same checks still require the count to include a late arrival and exclude a survivor from the stopped count.

## What was run

- [Native macOS run 45114710678 on main](https://github.com/Expectrail/Expectrail/actions/runs/45114710678) reported the original assertion failure: two processes counted as stopped when only one should have been.
- On Linux, forcing the backend without `/proc` and providing an empty process table reproduced the original `(2, 2)` versus `(2, 1)` failure. The revised test passed under the same setup.
- All 19 focused lost-worker tests passed on Linux. The full suite ran 6,086 tests and passed with 57 skips on main base `4b6ba69`.

## Not done

A native run on the revised test is pending. The remaining process-handle tests are outside this slice.

## Files

- `tests/test_orchestrator.py`
