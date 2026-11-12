# A step beside the player is not the ground under it: the edges are the player's own (#348)

## What changed
The first run on games the team did not write rejected Godot's kinematic character demo,
unchanged. The trial's log showed the player standing on the floor while, 20 px before a step one
tile high, the logged ground jumped up to the step's top. `_ground_under` in
`harness/godot/expectrail_harness.gd` asks for the highest solid surface under the body's centre and
its two edges, and the edges were always the bundled robot's, 20 px either side. The demo's player
is 14 px wide: a column 20 px out was inside the step.

- The edges are the player's own: half the width of its collision shapes, less 1.25 px. With no
  shape to measure, the robot's 20 px as before. The robot's own shape is 42.5 px wide, so its
  edges are exactly where they were.
- `tests/projects/stepped-ground`: a level built in code (a floor, a gap, a 64 px step) and a body
  24 px wide moved along it.
- `tests/routes/slope.json`: the bundled game walked up its level's slope.
- `tests/test_ground_under.py`, and a step in the CI job `capture-smoke` that runs it with the real
  engine and a skip counted as a failure.
- `docs/harness.md`, "The ground under the player".

**The first attempt in this pull request was wrong and is gone.** It took the surface under the
centre whenever there was one and asked the edges only without it. The merge guard's first review
measured what that costs with the real engine: on the bundled level's slope the ground was read up
to 23.7 px lower than main reads it, so a robot sunk by up to about 40 px would have passed where
main stops at about 21; and a body half off a ledge was measured against the floor 64 px below.
The three columns are kept. What was wrong was their distance, not their number.

## What was run (Godot 4.7.2)
- The new level: the step's top is the ground from x = 438 to 522, where this body's own edge is
  over the step; the floor before and after; no ground from x = 204 to 244 over the gap.
- The same tests on main's harness: 2 fail (the step is the ground from x = 428). On the first
  attempt: 4 fail (the ledge, the step, the gap and the slope).
- The bundled game on `tests/routes/slope.json`, main's harness and this one: all 420 rows are the
  same. On the slope the robot's feet are 1.15 to 1.38 px above the logged ground in every one of
  120 on-floor rows.
- The bundled game, routes `smoke`, `coins`, `combat` and `traversal`: no row of any trace differs
  from main's harness, and every frame's sha256 is the same.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_ground_under`: 7 tests, OK.
- The real sample: accept, reject, accept, each as expected.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, merged with main at 25d8585: 2265 tests, OK, 26 skipped.

## Not done
- The check still takes the feet to be 13.25 px below the origin (#259). The kinematic demo's are
  7.2 px below, so it is read 6 px lower than it stands: inside the 20 px tolerance, and wrong.
- Platforms that are bodies and not tiles have no ground line.
- A player whose collision shapes change size while it plays is measured with the shapes it has in
  that tick. Not tested.
- Not run here after the rework: `harness.check_seeded`; CI's `seeded-bugs` job runs it.

## Files
`harness/godot/expectrail_harness.gd`, `tests/projects/stepped-ground/` (`project/project.godot`,
`project/main.tscn`, `project/main.gd`, `routes/walk.json`), `tests/routes/slope.json`,
`tests/test_ground_under.py`, `.github/workflows/ci.yml`, `docs/harness.md`,
`docs/outside-projects.md`
