# The capture spike: a supervisor-owned display grabs every frame, and a rewritten frame shows (#246)

## What changed
A research tool and its findings, no product code. `python3 -m tools.capture_spike` replays the bundled
game the way `harness.run` does, but on an Xvfb the supervisor starts with `-fbdir` (the screen kept as a
file in a folder only the supervisor's user can open), with Godot running as another user (`setpriv`,
uid 65534). Approach 1 holds the engine after each frame (`step.gd`) and grabs the screen; approach 2
grabs at random moments with nothing added inside the game. `forge.gd` stands in for a change that
rewrites ten of Movie Maker's frames. `docs/capture-spike.md` records the runs, the slowdown, what the
game's user could reach, what the spike does not settle, and the recommendation: implement approach 1
with the replay sandbox as a follow-up after the fund; until then `isolated` stays the top grade.

## What was run
- The spike, on this machine (root, Godot 4.7.2, Mesa llvmpipe, Xvfb, no bubblewrap), bundled game,
  smoke route, 18 runs, numbers in `docs/capture-spike.md`:
  - approach 1, 4 clean runs: 480 of 480 grabs equal to Movie Maker's frame of the same index; with the
    forger, frames 50 to 59 differ and the other 110 are equal; +38 % wall time;
  - approach 2, 5 clean runs: 0 unexplained grabs, 0 to 4 torn; 5 forged runs: 27 to 29 unexplained, all
    between frames 49 and 60; +11 %;
  - every attempt by the game's user on the screen file, its folder, the display server's signals and
    memory was refused;
  - `trace.json` was the same in every mode and in a plain `harness.run` replay.
- `python3 -m unittest tests.test_capture_spike`: 14 tests, OK (NumPy and Pillow present here).
- The full suite merged with main: see the pull request.

## Not done
- Not run with bubblewrap, on a CI runner, on another game, with a GPU renderer, or under load.
- No search of Godot's or Mesa's documentation beyond Xvfb's `-fbdir`.
- The follow-up issue for the protected capture is for Sean to agree to.
- In CI's test job NumPy and Pillow are not installed, so 10 of the 14 new tests skip there; the 4
  tests of the screen-file header and the step summary run everywhere.

## Files
- `tools/capture_spike/__init__.py`, `__main__.py`, `spike.py`, `step.gd`, `forge.gd`
- `tests/test_capture_spike.py`
- `docs/capture-spike.md`
- `docs/new-work/2026-11-15-capture-spike.md`
- `.gitignore`: `tools/capture_spike/` is kept (every other new folder under `tools/` is ignored)
