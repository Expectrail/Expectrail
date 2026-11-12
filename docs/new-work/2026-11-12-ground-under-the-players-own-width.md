# A step beside the player is not the ground under it: the edges are the player's own (#348)

## What changed
The first run on games the team did not write rejected Godot's kinematic character demo,
unchanged. The trial's log showed the player standing on the floor while, 20 px before a step one
tile high, the logged ground jumped up to the step's top. `_ground_under` in
`harness/godot/expectrail_harness.gd` asks for the highest solid surface under the body's centre and
its two edges, and the edges were always the bundled robot's, 20 px either side. The demo's player
is 14 px wide: a column 20 px out was inside the step.

- The edges are the player's own: the leftmost and rightmost points of its collision
  (`CollisionShape2D` and `CollisionPolygon2D` children that are not disabled), measured where
  the body is in the world, each pulled in by 1.25 px. The third column is midway between them.
  With nothing to measure, the robot's 20 px as before. The robot's own shape is 42.5 px wide and
  centred, so its columns are exactly where they were.
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

**The second version was wrong for a scaled body.** It took the shape's own numbers, not where
the body is in the world. The merge guard's second review measured it: the test level's body at
scale 2 is 48 px wide, and the step was its ground only from x = 438, where main said 428 and the
body's real edge is over the step from 424. The ends are now measured in the world (`_body_span`,
which replaces `_edge_reach`). The review listed two gaps to write down, a polygon for the collision
and a shape off to one side; both are measured now and held by tests, because Godot players do
come that way.

**What this costs, and is now said in the code and in `docs/harness.md`:** the columns belong to
the game being measured. A change that makes the player's collision narrower or wider moves them,
and can move the ground the harness logs. The guard measured one: the robot's shape made 6 px wide
and lifted 10 px, on the slope route, has its feet 17.2 to 32.8 px below the ground main's harness
logs and 5.9 to 10.0 px below the ground this branch logs. The gate reads the logged ground. The
fix loop's verifier works the ground out again from the clean level with a fixed 20 px and is not
affected. I have not run that patch myself; the numbers are the guard's, on the head before this
one, and that shape's columns are the same on this one.

## What was run (Godot 4.7.2)
- The new level: the step's top is the ground from x = 438 to 522, where this body's own edge is
  over the step; the floor before and after; no ground from x = 204 to 244 over the gap.
- The level again with the body changed in the scene, each a test in `BodyInTheWorldTest`:
  at scale 2 the step is the ground from x = 426 and there is no ground from x = 216 to 232; at
  scale 0.5, from x = 444 to 516 and no ground from 198 to 250; the whole scene at 1.5, no ground
  from x = 306 to 366 (the shape's own numbers would say 300 to 372); the shape 10 px to one side,
  the step from x = 428 to 512; that body mirrored, the step from x = 448; a 24 px polygon, the same
  as the 24 px shape; the only shape disabled, the robot's 20 px.
- The 14 tests on main's harness: 8 fail and the script test errors. On the head before this one
  (`fced308`): 6 fail (every test of a changed body but the disabled shape) and the script test
  errors. On the first attempt: 4 of the first 7 failed (the ledge, the step, the gap, the slope).
- The bundled game on `tests/routes/slope.json`, main's harness and this one: all 420 rows are the
  same. On the slope the robot's feet are 1.15 to 1.38 px above the logged ground in every one of
  120 on-floor rows.
- The bundled game, routes `smoke`, `coins`, `combat`, `traversal` and the slope route, main's
  harness against this head: no row of any trace differs (240, 240, 180, 360 and 420 rows), and
  every frame's sha256 is the same (120, 120, 90, 180 and 210 frames).
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_ground_under`: 14 tests, OK.
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
