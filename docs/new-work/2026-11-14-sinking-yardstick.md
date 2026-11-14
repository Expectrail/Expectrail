# The position log keeps the feet as the bottom (#259)

## What changed

The merge guard rejected pull request #430. Using a trace row's `body` as the player's box made
sinking v1 pass: that bug lifts the collision 26 px, physics rests the collision on the ground,
and the origin (and the feet) sit 26 px lower. The collision's own bottom is then on the ground,
inside the 20 px tolerance, so the ground check passed a robot that has sunk.

`agents/observations.py` now takes the width and height from `body` when the row has a
positive-area box, and keeps the bottom where it was without a body: the feet (origin plus
`FEET_OFFSET`) when the camera is logged, and the origin on the old no-camera fallback. The
collision's own bottom is not used. A row with no box, or a box that is not a finite positive
area, still uses the bundled constants. Coins and the ground search are unchanged.

The docs that said the observation box is `body` now say this.

## What was run

`/tmp/py312/bin/python -m unittest discover -s tests -t .` (CPython 3.12.15):
`Ran 3277 tests in 375.100s`, `OK (skipped=59)`.

`tests/test_project_config.py` builds a clean trace and a sinking-v1 trace from the measured
body (42.5 by 54.5, bottom `FEET_OFFSET` below the origin on the clean game, collision lifted
26 px with its bottom still on the ground). `evaluate` of `player-stays-above-ground` is `pass`
on the clean trace and `fail` on the sunk one. A row with no `body` still ends at the feet on
the bundled constants. `tests/test_engine_check.py` has no `body` and still places the robot at
`[680.0, 406.5, 760.0, 526.5]`.

The CI `seeded-bugs` job was not re-run here. It needs the engine traces under
`runs/seeded-check`.

## Not done

Not pushed. Pull request #430 is still open at `6aecc16` and is not on main (`origin/main` is
`5433b5e`). Issue #260 is not rebuilt in this change. The trace schema and its example are
unchanged; they are updated when `init` and `inspect` are rebuilt on main after #430 has merged.

The 59 skips were not listed. No model was called and nothing was spent.

## Files

- `agents/observations.py`
- `docs/harness.md`
- `docs/project-config.md`
- `docs/new-work/2026-11-14-sinking-yardstick.md`
- `tests/test_project_config.py`

## Architect run

Linux. The patch applied cleanly on `6aecc16` (the head the merge guard reviewed) as `ba5294c`. Main (`0c23a52`, 45 commits ahead) was then merged into the branch as `82ee5dd`. It had two registry conflicts, both resolved by keeping both sides: `setup.py`'s bundled modules (`project_config` with main's `approval` and `repair`) and `expectrail/contracts.py`'s `V1_FORMATS` (`project/v1` with main's `repair-run/v1`). Godot 4.7.2 from `harness/get_godot.sh`, under `xvfb-run`.

- `python -m harness.check_seeded --out runs/seeded-check`: exit 0, every seeded bug differs from clean. Run without bubblewrap here (`bwrap` is not installed), so the replays were not sandboxed; CI's job sandboxes them.
- CI's "position log sees a robot resting too low" step, run over those traces: `{'clean': 'pass', 'sinking_v1': 'fail', 'sinking_v2': 'pass'}`, matching the assertion that failed in CI run 43568604937.
- `EXPECTRAIL_ENGINE_TESTS=required` on `tests.test_body_box`, `test_event_input`, `test_ground_under`, `test_pause_input`, `test_second_project`, `test_auto_route_engine`, `test_unknown_actions`: `Ran 69 tests`, `OK`, none skipped.
- `python3 -m unittest discover -s tests -t .` on the merged result: `Ran 3415 tests`, `OK (skipped=31)`.

Not run: the hosted CI jobs (they run on push), the release gate suite. No model was called and nothing was spent.
