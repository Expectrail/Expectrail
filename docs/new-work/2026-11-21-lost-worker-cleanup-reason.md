# Check the lost-worker cleanup message on hosts without process handles (#378)

## What changed

The lost-worker test now expects the full process-number explanation on hosts without process handles. The existing exact message check stays in place on hosts with handles. Both cases still check that the child has stopped, the job has no remaining processes, and asking again returns the same status.

## What was run

- [Native macOS run 44946844750](https://github.com/Expectrail/Expectrail/actions/runs/44946844750) showed both child-process cases reaching the message assertion after the child had stopped. Both failed on the extra process-number explanation.
- On Linux, forcing `pidfd_open` to raise `ENOSYS` reproduced both message failures before the change. The targeted test passed after the change with and without that simulation.
- The full Linux suite ran 6,030 tests in 902.434 seconds and passed with 57 skips on the branch based on `41bfa0d`.

## Not done

A native macOS run of this change is pending. Other macOS suite failures remain open under #378.

## Files

- `tests/test_orchestrator.py`
