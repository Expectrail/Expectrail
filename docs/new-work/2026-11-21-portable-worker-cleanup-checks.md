# Exercise both process cleanup paths in lost-worker tests (#378)

## What changed

The marker recheck test requires handle-based signalling on Linux and verifies the exact process-number signal on hosts without `/proc`. Both paths still check that a mismatched marker leaves the process alive. The discovery failure test now checks that the lost job records the appropriate cleanup error on either path.

## What was run

- [Advisory macOS run 44979948322](https://github.com/Expectrail/Expectrail/actions/runs/44979948322) recorded the original marker and discovery test failures.
- The original tests reproduced one failure and one error on Linux using the existing Darwin `ps` fixture. Both revised tests passed under the same simulation and on the normal Linux path.
- The full Linux suite ran 6,037 tests in 927.892 seconds and passed with 57 skips on the branch based on `4d2e095`.

## Not done

Native macOS verification of the revised tests is pending. Other macOS suite failures remain under #378.

## Files

- `tests/test_orchestrator.py`
