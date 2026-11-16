# Stray warnings kept out of captured command output, and the leaked sockets closed (#561)

## What changed
The nightly platform test saw `tests.test_ingest_generated` fail once in the full suite: the command
exited 2 (needs-review, as expected), but the captured text was not JSON at its first character. The
test sent the command's stdout and stderr into one buffer. The full suite prints `ResourceWarning:
unclosed socket` lines, and such a warning is printed when the garbage collector runs, which can be in
the middle of any later test's in-process command. `tests/test_no_stray_output.py` shows that a socket
collected mid-command puts the warning into such a buffer and breaks the parse.

- **The tests.** `tests/cli_capture.py` has `command_output(buffer)`. It redirects stdout and stderr
  as before and records warnings while the command runs, then prints each one to the real stderr
  afterwards, so none is hidden. Whatever the command itself writes still lands in the buffer, so a
  test that parses it as JSON still fails when the command prints anything else. The seven test files
  that sent both streams into one buffer use it: `test_ingest_generated`, `test_ingest_repair`,
  `test_init_inspect`, `test_playtest_ingest`, `test_project_audit`, `test_repair_command`,
  `test_trial_stops`. No assertion changed.
- **The sockets.** The warnings in a full-suite log here came from three places:
  - `agents/check_pages.py` shut its page server down but never closed its listening socket (6
    warnings). It now calls `server_close()`. So do `tools/runit_smoke.py` and
    `tests/test_trust_store_rotation.py`, which had the same pattern.
  - `agents/gateway_bridge.py`'s pumps shut both sockets down but never closed them, and a refused
    upstream socket was left open. `join()` now starts both directions, and the second one to stop
    closes both sockets. `agents/gateway.py`'s Unix bridge uses the same `join()`.
  - One more warning (an unclosed `127.0.0.1` socket printed from `unittest/case.py`) was not traced.

## What was run
- `python3 -m unittest tests.test_no_stray_output`: 7 tests, OK.
  - Without the helper's warning capture: 1 error. Without `server_close()` in check_pages: 1
    failure. With the old gateway bridge: 1 failure and 1 error.
- The seven changed test files, `test_check_pages` and `test_gateway`: OK.
- Full suite on the branch merged with main at a721e67: 4,434 tests, OK, 49 skipped (580 s). Its log
  has no unclosed-socket warning (the run of #547's branch just before had 11). Two `unclosed file
  <_io.TextIOWrapper>` warnings remain, printed from a test's cleanups; not traced.
- Not shown: that this was the cause of the one failure the nightly test saw. Its buffer was not kept.
  The mechanism is shown by a test, and the leaked sockets were in that run's log.

## Not done
- The untraced `127.0.0.1` socket warning above. It did not appear in the full run after the fix,
  which does not show it is gone.
- The two unclosed-file warnings. The helper keeps them out of the parsed buffers either way.

## Files
- `tests/cli_capture.py`, `tests/test_no_stray_output.py`
- `tests/test_ingest_generated.py`, `tests/test_ingest_repair.py`, `tests/test_init_inspect.py`,
  `tests/test_playtest_ingest.py`, `tests/test_project_audit.py`, `tests/test_repair_command.py`,
  `tests/test_trial_stops.py`, `tests/test_trust_store_rotation.py`
- `agents/check_pages.py`, `agents/gateway_bridge.py`, `agents/gateway.py`, `tools/runit_smoke.py`
- `docs/new-work/2026-11-16-no-stray-output.md`
