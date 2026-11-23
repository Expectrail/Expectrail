# Exercise worker cleanup with a high-numbered descriptor on macOS (#378)

## What changed

The lost-worker test holds a real file descriptor numbered at least 1024 on the process-number path and checks that a real marked child is stopped. The Linux path still requires signalling a real high-numbered pidfd without falling back to the process number.

## What was run

- [Native macOS run 45231368166](https://github.com/Expectrail/Expectrail/actions/runs/45231368166) recorded the original missing-`pidfd_open` error.
- On Linux, removing `pidfd_open` and using the existing Darwin process-table fixture reproduced that error before the change. The revised test passed under the same simulation with a real child and descriptor.
- All 19 focused lost-worker tests passed on Linux. The full suite ran 6,091 tests and passed with 57 skips on main base `b490441`.

## Not done

Native macOS verification of the revised test is pending. The separate handle-fallback test still has native failures.

## Files

- `tests/test_orchestrator.py`
