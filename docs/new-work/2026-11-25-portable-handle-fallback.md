# Run the handle-error fallback test on macOS (#378)

## What changed

On hosts without `/proc`, the test supplies a pollable pipe for the Linux process handle and injects the same syscall errors. Discovery and child cleanup use the host process backend. Linux still exercises the existing real pidfd path.

## What was run

- [Native macOS run 45692085668](https://github.com/Expectrail/Expectrail/actions/runs/45692085668) reported one failure and four errors from this test.
- On Linux, the Darwin process-table fixture with both pidfd APIs removed reproduced all five original outcomes. The revised test passed the same control.
- All 19 focused lost-worker tests passed on Linux. The full suite ran 6,103 tests and passed with 57 skips on main base `e75394e`.

## Not done

Native macOS verification of the revised test is pending.

## Files

- `tests/test_orchestrator.py`
