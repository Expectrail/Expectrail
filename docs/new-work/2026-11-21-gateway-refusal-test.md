# Verify gateway socket cleanup directly after a refused connection (#378)

## What changed

The refused-upstream test feeds one real client socket into the gateway bridge's serve loop and connects to a bound Unix socket that is not listening. It checks that the bridge closes both file descriptors before test cleanup. The fixture uses a short Unix socket path and does not start a listening TCP socket or a background thread.

## What was run

- On Linux, `python3 -m unittest tests.test_no_stray_output -v` passed all seven tests.
- Simulating `ENOTCONN` on listening TCP socket shutdown caused one error in the old test. The revised test passed with the same simulation.
- In two separate in-memory runs, removing the client close or the upstream close caused the revised test to fail.
- The full Linux suite, `python3 -m unittest discover -s tests -t .`, ran 5,986 tests with 57 skips on November 21, 2026. It passed on the branch based on `1f6ad43`.

## Not done

The replacement still needs a native macOS run. This change covers one test from #378. The job-cancellation and lost-worker cleanup work remains separate.

## Files

- `tests/test_no_stray_output.py`
