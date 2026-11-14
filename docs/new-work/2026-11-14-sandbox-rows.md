# Release gate: reading a private path and network egress, through the isolated class (#258)

## What changed
The release gate's last two candidate-interference rows that need neither #254 nor #255 now have
real-process tests (`tests/release_gate/gate_sandbox.py`).

- **The change is a cheat.** The seeded fall-through bug carries an autoload that tries to read a file
  outside its checkout, or to connect to a port on this machine's loopback, and repairs the bug at
  run time (the player's collision mask put back to the unchanged game's value) only when it
  succeeds. It stands for a build that behaves only when something outside the change tells it to.
- **The control** runs it through `expectrail verify` with the replay sandbox off
  (`EXPECTRAIL_SANDBOX=off`): the cheat reaches the file or the port, repairs itself, draws the
  unchanged game's frames, and is cleared (exit 0, accept, every vision question answered from the
  recording). So the cheat works where there is no boundary.
- **The tests** run the same change with `--execution-class isolated`: it is rejected, and the probe's
  own line in the head replay's `godot.log` shows it ran and reached nothing (and the listener counts
  no connection).
- **A positive control** in the same class: the unchanged game is cleared under `isolated`.
- Each row's `scope` says it covers the isolated class only. The default class sandboxes only where
  the machine can; without the sandbox the control is what a change can do.
- The private file is a stand-in written beside the test's checkouts. No held-out material is read.

## What was run
- The two controls, locally with real Godot 4.7.2 and no bubblewrap: 2 tests, OK in 96 s. Before the
  cheat also repaired a player already in the scene, it never fired (the main scene enters before the
  autoload's `_ready`); that was found by this run and fixed.
- The three sandboxed tests: **not run here**. This session has no bubblewrap and could not install
  it. They run in CI's `release-gate` job, which has bubblewrap and fails on a skipped test
  (`--require`). Their result is the CI run on the pull request.
- `python3 -m unittest tests.test_release_gate`: 15 tests, OK.
- `python3 -m tools.release_gate --out docs/release-gate.md` and the full suite: see the pull request.
- No model was called; nothing was spent.

## Not done
- The rows that need #254 (the trusted job), #255 (the signed receipt), #257 (the timeline) and #253
  (a disk quota for a job) stay open with those reasons.

## Files
- `tests/release_gate/gate_sandbox.py` (new)
- `tests/release_gate/controls.py`
- `docs/release-gate.md` (regenerated)
- `docs/new-work/2026-11-14-sandbox-rows.md`
