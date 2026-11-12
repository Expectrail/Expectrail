# The fixer runs in a session of its own and cannot open its starter's terminal (#309)

## What changed

`agents/sandbox.py` started the fixer in bubblewrap without `--new-session`. bubblewrap's `--dev`
provides `/dev/tty`, so a fixer started from a terminal could open that terminal, and on a kernel
that still allows `TIOCSTI` type into the shell behind it. The merge guard found the same gap in the
replay's sandbox (#304); this is the same fix for the fixer's.

- `_bwrap_cmd` passes `--new-session`, and so does the probe in `_bwrap_usable`, so the check for
  "bubblewrap works here" runs what the fixer runs.
- `run_sandboxed` gives the bubblewrap fixer no input (`stdin` is `/dev/null`). It used to inherit
  the loop's, which is the terminal when the loop is started from one. Nothing passes the fixer
  input today: Muse Code and the bring-your-own agents get their task as arguments and files.
- The fixer is now in another session than the loop, so a signal to the loop's process group does
  not reach it. bubblewrap going is what ends it (`--die-with-parent`, and the PID namespace ends
  with bubblewrap). Three tests hold that: a time limit, a killed loop, a signalled process group.

## What was run

- `python3 -m unittest discover -s tests -t .` locally: 2000 tests, OK, 21 skipped. Four of the skips are the
  new tests that start bubblewrap: this machine has none. The other 17 skip on main too.
- Locally, without bubblewrap: the command and the probe both carry `--new-session`; the fixer gets
  no input; the control (a program outside any sandbox, started under a pseudo-terminal, opens
  `/dev/tty`).
- In real bubblewrap: only in CI. The `agents-sandbox` job now runs `tests.test_guard.BwrapSessionTest`
  with `EXPECTRAIL_REQUIRE_BWRAP=1`, where a skip is a failure. The run is linked on the pull request.
  Until that run is green, "the fixer cannot open the terminal" is not shown.
- Not run: a live Muse Code or bring-your-own-agent fix with the change (it spends model budget). In
  CI those loops already ran without a terminal; a loop started from a developer's terminal now gets
  the same.

## Not done

- The capability ledger's `fixer-sandbox` row is not updated: its run evidence should cite a run on
  main that includes these tests, which exists only after this merges.
- The fixer's sandbox still has none of the replay sandbox's other limits (no size or process limits,
  the environment is an allowlist and not cleared, the network stays on unless the key gateway is used).
- The Docker fallback is unchanged: `docker run` without `-i` or `-t` gives the container no terminal.

## Files

- `agents/sandbox.py`
- `tests/test_guard.py`
- `.github/workflows/ci.yml` (one step: the `agents-sandbox` job runs the new test class)
- `docs/replay-sandbox.md`
