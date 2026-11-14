# The ground's columns for thin bodies, turned round shapes, child shapes and growing shapes (#354)

## What changed
The harness reads the ground under the player at three columns: its middle and its two ends, the
ends being its own collision measured in the world (#349). #354 listed the cases that left open.

- **Gap 1, a body 2.5 px wide or less.** It was treated as having no collision and given the
  robot's 20 px either side, so a body 2 px wide had a step 18 px away as its ground. Its middle is
  now asked, as all three columns (`_body_span`). The fallback of 20 px stays for a player with
  nothing to measure.
- **Gap 3, a turned circle or capsule.** It was measured by the corners of its box: a circle of
  radius 12 turned 45 degrees was 33.9 px wide. `_shape_outline` now measures a circle or capsule by
  64 points on its curve, a polygon shape by its points, a segment by its ends, anything else by its
  box as before (exact for a rectangle). The same measure gives the trace's `body` box, so a turned
  round shape's box is now its real one too. No contract changes.
- **Gap 3, a shape on a child body.** Decided and written down, with a test: only the body's direct
  children collide for it in Godot, so a shape on a child area or body (a hitbox) is not the
  player's and does not widen the columns. That was already the behaviour; it now has a test.
- **Gap 3, a shape that changes size while the game plays.** Already measured tick by tick; it now
  has a test (a 24 px box made 48 px wide half way along the level).
- **Gap 2, whose collision sets the gate's columns.** A choice between two designs, written down in
  `docs/harness.md` ("Not decided") for Sean: the candidate's own (today) or the base commit's. The
  harness keeps the candidate's own until he chooses. `NarrowedRobotOnSlopeTest` holds today's rule
  and the size of what is at stake on the slope.

## What was run
All with Godot 4.7.2 on this session's machine.

- `python3 -m unittest tests.test_ground_under -v`: 32 tests, OK, before `NarrowedRobotOnSlopeTest`
  was added; that class and `ScriptTest` then: 5 tests, OK.
- The eight new `ShapesTest` tests against main's harness (`harness/godot/expectrail_harness.gd`
  from `origin/main`, the tests from this branch): 4 failed (the 2 px body, the 2 px body off its
  origin, the turned circle, the turned capsule) and 4 passed (the 4 px body, the upright capsule,
  the child area, the growing shape). So the four that fail are what this change fixes, and the
  four that pass hold behaviour that was right and untested.
- The narrowed robot (6 px wide, lifted 10 px) on `tests/routes/slope.json`: its feet 5.9 to 10.0 px
  below the ground logged at its own columns; with the harness's span fixed at the robot's 20 px,
  17.2 to 32.8 px. Both match the merge guard's numbers on #349. The robot unchanged: -1.4 to -1.1
  either way.
- The bundled game's five routes (`smoke`, `coins`, `combat`, `traversal`, `tests/routes/slope.json`)
  with main's harness and with this branch's: every row of every trace byte for byte the same.
- `python3 -m unittest discover -s tests -t .` on this branch (main at 33d0a50, the submission
  commit fetched, Godot present): 3,514 tests, OK, 31 skipped.

## Not done
- Gap 2's choice is Sean's. If he chooses the base commit's columns, the harness needs the base
  span as an input, a trace header field, and `NarrowedRobotOnSlopeTest` changes with it. Not
  tested through the gate's own path, since no approved check or route reaches a slope today.
- Platforms are still measured by their shapes' boxes (`_platform_shapes`); only the player's own
  collision gets the curve. A round platform turned is rare; not changed here.

## Files
- `harness/godot/expectrail_harness.gd`
- `tests/test_ground_under.py`
- `docs/harness.md`
- `docs/new-work/2026-11-14-ground-columns-shapes.md`
