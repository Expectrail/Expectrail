# The anchored rule in pairs: each frame against the unchanged game's same frame (#330)

## What changed
The range rule failed a clean route on one frame in 36 (the robot in front of a tree, answered as
robot and trunk together). The idea of asking the frames either side was measured and dropped: run
43318368572 shows that answer lasting nine frames in a row. What replaces it is the comparison
Expectrail already makes everywhere else: the changed game against the unchanged game on the same
route.

- `agents/anchor_rule.py`: `pair` and `--pair FILE:RUN`. A frame is compared where the engine has
  the player in the same place in both games; the four measures must agree within a tolerance
  (6 px by default). A frame the engine moved, a frame the unchanged game has no box for and runs
  of different routes are not compared, and a run with any of those is needs-review, never a pass.
  The range rule (`--calibrate`) is unchanged.
- `agents/sam_anchor.py`: each run's route (name and digest, from its `replay.json`) is recorded in
  the report, so that frames of different routes are never paired.
- `tests/data/sam-anchor/bundled-lift-14-traversal-frames-15-25.json`: the 11 frames around the
  slip, from run 43318368572. The three files already there gain each run's route name, added by
  hand from the workflow's inputs and said so in the files.
- `.github/workflows/sam-probe.yml`, probe mode: input `route` replays the clean game and the
  seeded bugs on another route; after an anchored probe the pairs' table is made as well as the
  range rule's. No secret, environment or permission is added, and neither new step holds a key
  that it did not hold before.
- `docs/sam.md`: the 11-frame result, the pairs, what they say on the recorded answers, and the
  run that would test the idea.

## What was run
- `python3 -m unittest tests.test_anchor_rule tests.test_sam_anchor`: 84 tests, OK.
- The pairs over the recorded answers at mid-body, every run against clean: missing-texture v1 and
  v2 pass (0 of 13 differ), layering fails (9 of 13), sinking v2 fails (13 of 13, "above 3 against
  29 unchanged; below 56 against 30 unchanged"), sinking v1 and fall-through are needs-review (the
  engine moved the player in every asked frame). Missing-texture passes from a tolerance of 5 px;
  sinking v2 differs in all 13 frames up to 25 px.
- The three other clean routes paired against the smoke route's clean run before routes were
  recorded: `clean-combat` failed on a frame at the same place with another pose (width 38 against
  46). That is why routes are recorded and different routes refused.
- `python3 -m harness.check_seeded --route harness/routes/traversal.json` (Godot 4.7.2): 8 of 8 ok,
  exit 0. The probe's `--dry-run` over its clean, missing-texture v1, layering v1 and sinking v2
  runs at `--lift 14`: 52 requests. Their `replay.json` gives the route as `traversal`.
- Every shell step of the probe job passes `bash -n`; the workflow parses with 15 inputs;
  `python3 -m tools.merge_guard`: nothing to report.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, on main at aa290b1 with #360: 2442 tests, OK, 26 skipped.
- **Not run: anything against the service, and the workflow's new steps on a runner.**

## Not done
- **The test of the idea.** Whether a harmless change on a route where the unchanged game slips
  gets the same slipped boxes. That is one run for Sean (52 images, $0.13): `route` traversal,
  `runs` clean,missing-texture_v1,layering_v1,sinking_v2, `lift` 14, `anchor` ticked.
- A change that moves the player slightly and changes nothing else leaves every frame "moved" and
  the pairs silent. The range rule set on the unchanged game's run of the same route is the
  obvious fallback; it is not wired together here.
- The tolerance is 6 px from 13 frame pairs. A drawing moved by 6 px or less is not seen.
- Still a probe's rule. No verdict reads it.

## Files
`agents/anchor_rule.py`, `agents/sam_anchor.py`, `tests/test_anchor_rule.py`,
`tests/test_sam_anchor.py`, `tests/data/sam-anchor/` (four files), `.github/workflows/sam-probe.yml`,
`docs/sam.md`
