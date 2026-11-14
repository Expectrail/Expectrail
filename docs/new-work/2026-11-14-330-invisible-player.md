# A broken copy only vision can catch (#330)

## What changed

- `tests/outside/kinematic-character/changes/invisible.patch` hides the player's sprite
  (`visible = false`); the player moves exactly as before. Listed in `tests/outside/projects.json`
  with `expect: needs-review`.
- Why: the two existing changes do not test the visual observer. `broken` is rejected by the engine
  alone, and `harmless` should pass both. A hidden player passes the engine's checks, so the verdict
  turns on vision: with vision it must not be accepted. This is #330's "prove on broken copies" for
  a defect the engine's record cannot see.
- `tests/test_outside_vision.py` pins its stand-in project (and the list `main` reads) to the two
  changes its stand-in replays make. Its CLI test patched `FramesObserver`, which the judge no longer
  builds since #442; it now patches the model client with the stand-in transport and checks the
  calibration, which asks nothing because these traces log no body box.

## What was run

- `python3 -m unittest discover -s tests -t .` on #442 merged with main 5433b5e: 3,344 tests, OK (31 skipped).
- `python3 -m unittest tests.test_outside_vision tests.test_outside_trial tests.test_anchored_observer`: OK.
- The real capture of the new change (Godot, sandboxed) runs in CI's outside trial on this PR,
  which is path-filtered to `tests/outside/`.

## Files

- `tests/outside/kinematic-character/changes/invisible.patch`
- `tests/outside/projects.json`
- `tests/test_outside_vision.py`
- `docs/outside-projects.md`
- `docs/new-work/2026-11-14-330-invisible-player.md`
