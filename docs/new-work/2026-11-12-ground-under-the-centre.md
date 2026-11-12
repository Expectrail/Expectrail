# A step beside the player is not the ground under it (#348)

## What changed
The first run on games the team did not write rejected Godot's kinematic character demo,
unchanged. The trial's log showed why: the player stands on the floor and does not move in y, and
20 px before a step one tile high the logged ground jumps up to the step's top. `_ground_under` in
`harness/godot/expectrail_harness.gd` took the highest solid surface under the body's centre and
its two edges, so a step beside the player was read as the ground under it.

- The surface under the centre is the ground when there is one. The edges are asked only when the
  centre has none.
- `tests/projects/stepped-ground`: a level built in code for the test (a floor, a gap, a 64 px
  step) and a marker that walks along it.
- `tests/test_ground_under.py`, and a step in the CI job `capture-smoke` that runs it with the real
  engine and a skip counted as a failure.
- `docs/harness.md`, "The ground under the player".

## What was run
- The new level with main's harness (Godot 4.7.2): the ground is 320 (the floor) until x = 428 and
  256 (the step's top) from there to the end, 20 px before the step and 20 px after it. With this
  change: 256 only from x = 448 to 512, where the centre is over the step; 320 beside it; no ground
  from x = 212 to 236, over the gap, where nothing is under the body.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_ground_under`: 5 tests, OK.
- The bundled game, routes `smoke`, `coins`, `combat` and `traversal`, with main's harness and with
  this one: the ground is the same in every row of every trace, nothing else in the traces
  differs, and every frame's sha256 is the same.
- `python3 -m harness.check_seeded` (the clean game and every seeded bug, rendered): 8 of 8 ok, exit 0.
- The real sample: accept, reject, accept, each as expected.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2,241 tests, OK, 26 skipped.

## Not done
- The kinematic character demo itself was not run by me. This pull request touches
  `harness/godot/`, so the outside trial runs on it once #345 is on main; until then its next run
  is the evidence, and `docs/outside-projects.md` is updated from that run only.
- The sizes are still the bundled robot's (#259). A project whose player is wider than 40 px, or
  whose origin is not near its feet, is measured with the wrong numbers.
- Platforms that are bodies and not tiles have no ground line.
- On a slope the surface under the centre is lower than the highest point under the body, so a
  player sunk by less than that difference is not seen there. The bundled level's routes do not
  show a difference; no test covers a slope.

## Files
`harness/godot/expectrail_harness.gd`, `tests/projects/stepped-ground/` (`project/project.godot`,
`project/main.tscn`, `project/main.gd`, `routes/walk.json`), `tests/test_ground_under.py`,
`.github/workflows/ci.yml`, `docs/harness.md`
