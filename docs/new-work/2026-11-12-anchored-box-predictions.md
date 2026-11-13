# The box against four predictions written before the run: three held, one half held (#330)

## What changed
Nothing in the code. The run that the four predictions of #364 were written for is recorded, with
how each fell.

- `tests/data/sam-anchor/bundled-box-48x68-smoke-and-clean-routes.json`: SAM's answers in run
  43337979278 (Sean's): the smoke route's clean game and eight seeded bugs, and the clean game on
  coins, combat and traversal, asked with a box of 48 by 68 game px.
- `tests/test_anchor_rule.py`, `PredictionsTest`: one test per prediction, named for how it fell,
  and three for what else the run showed.
- `docs/sam.md`: the table of predictions and outcomes.

## What was run
- Run 43337979278 is Sean's: 131 images, $0.33 counted. The predictions were in pull request #364
  and in a message to Sean before the run was started.
- Read from `anchor.json` on the results branch, by script: the four clean runs' confidences (49
  frames, lowest 0.867); the pairs for every run against the smoke route's clean run (both
  missing-texture runs 0 of 13, sinking v2 13 of 13, both layering runs 8 of 13); the one layering
  frame that differs at a confidence of 0.82 (frame 30), which I looked at on the contact sheets:
  the robot is half hidden behind a coin.
- `python3 -m unittest tests.test_anchor_rule`: 62 tests, OK.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, on #364's head: 2576 tests, OK, 27 skipped.

## Not done
- Two numbers I gave Sean in conversation were wrong and are right here: the fall in confidence at
  layering's frame 30 is 0.102, not 0.11, and the count of clean-looking frames asked with a box
  is 101, not 75.
- The box is still a probe: one game, a size typed in by hand, two kinds of drawing bug, every
  tenth frame. What it would take to put it in the verdict path is a design note for Sean, not
  written yet.

## Files
`tests/data/sam-anchor/bundled-box-48x68-smoke-and-clean-routes.json`, `tests/test_anchor_rule.py`,
`docs/sam.md`
