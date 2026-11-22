# Check disappearing processes on both cleanup paths (#378)

## What changed

The process-number test models a disappearing process at the call where each backend actually detects it. It still checks that a mismatched job marker prevents a signal. Standalone sleep fixtures use their own subprocess handles for teardown, so cleanup can reap the fixture without signalling an already empty process group.

## What was run

- [Native macOS run 44988345370](https://github.com/Expectrail/Expectrail/actions/runs/44988345370) recorded the original signalling assertion failure and group teardown error.
- On Linux, the original signalling test failed with a simulated Darwin process table, and the original teardown errored with a forced group-signal permission failure. The revised tests passed their respective simulations and the normal Linux path.
- All 19 lost-worker tests passed on Linux. The full Linux suite ran 6,038 tests and passed with 57 skips on the branch based on `7c08b92`.

## Not done

Native macOS verification of the revised tests and the remaining process-handle tests are open.

## Files

- `tests/test_orchestrator.py`
