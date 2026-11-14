# A broken copy only vision can catch (#330)

## What changed

- `tests/outside/kinematic-character/changes/invisible.patch` hides the player's sprite
  (`visible = false`); the player moves exactly as before. Listed in `tests/outside/projects.json`
  with `expect: needs-review`.
- Why: the two existing changes do not test the visual observer. `broken` is rejected by the engine
  alone, and `harmless` should pass both. A hidden player passes the engine's checks, so the verdict
  turns on vision: with vision it must not be accepted. This is #330's "prove on broken copies" for
  a defect the engine's record cannot see.
- `tests/test_outside_vision.py` (the guard's finding on #442): its CLI tests patched
  `FramesObserver`, which the judge no longer builds, so they passed whatever the code did. Now:
  - the fixture's trace rows carry the player's body box, so the calibration asks real frames;
  - the stand-in models are patched in where the judge builds its client (`MetaSamClient`);
  - the cap check is still made before any client is built;
  - a model that sees the player is calibrated (`check_calibration` passes, `enabled`), the
    unchanged game and the tint are accepted, and the broken copy is rejected with the anchored
    observer named in its record;
  - a model that echoes the box is not used: needs-review, "not calibrated" in the reasons;
  - the recording the live path writes, fed back through `judge --recording` with no client
    allowed, gives the same findings, counts and calibration rates.
  - It also pins its stand-in project (and the list `main` reads) to the two changes its stand-in
    replays make.

## What was run

- `python3 -m unittest discover -s tests -t .` on #442 merged with main 5433b5e: 3,344 tests, OK (31 skipped); with the guard's tests and main merged again: 3,349 tests, OK (31 skipped).
- `python3 -m unittest tests.test_outside_vision tests.test_outside_trial tests.test_anchored_observer`: OK.
- The real capture of the new change (Godot, sandboxed) runs in CI's outside trial on this PR,
  which is path-filtered to `tests/outside/`.

## Files

- `tests/outside/kinematic-character/changes/invisible.patch`
- `tests/outside/projects.json`
- `tests/test_outside_vision.py`
- `docs/outside-projects.md`
- `docs/new-work/2026-11-14-330-invisible-player.md`
