# The box, measured: both false alarms gone, and the pairs read the confidence (#330)

## What changed
- **The first run with a box is recorded.** Run 43335151089 (Sean's), the traversal route, a box
  of 48 by 68 game px around the robot's body. The harmless change passes the pairs with no frame
  differing; the two frames where a point slipped (20 and 100) come back as the robot alone in
  both games; the clean game's confidence is 0.87 to 0.95 and the bugs' is 0.69 or less in every
  frame where something is wrong. The answers are saved as
  `tests/data/sam-anchor/bundled-box-48x68-traversal-seeded.json`.
- **The pairs read the confidence.** `agents/anchor_rule.py`: a compared frame is also out when
  its confidence is more than 0.1 below the unchanged game's for the same frame (`--drop`). Only a
  fall counts, and only where both answers have a confidence. By size alone a box catches fewer
  frames than a point did, because SAM answers a hidden robot with scenery about the size of the
  box; the confidence is what tells those frames apart.
- `docs/sam.md`: the result, and four things that have to hold on the next run, written before
  that run exists.

## What was run
- Run 43335151089 is Sean's: 52 images, $0.13 counted. I read `anchor.json` and `anchor-pairs.md`
  from the results branch.
- The pairs with the drop over every recorded run: at mid-body with a point on smoke,
  missing-texture 0 of 13, layering 9 of 13, sinking v2 13 of 13 (unchanged by the drop); with a
  point on traversal, missing-texture 1 of 13 (the known false alarm), layering 8, sinking v2 13;
  with the box on traversal, missing-texture 0 of 13, layering 7 of 13, sinking v2 13 of 13.
- The largest fall in confidence over the 52 recorded harmless frame pairs: 0.03125.
- `python3 -m unittest tests.test_anchor_rule tests.test_sam_anchor`: 100 tests, OK.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, main at 2f7e35a: 2569 tests, OK, 27 skipped.

## Not done
- **The test of it.** 0.1 was chosen after seeing one route. The run that tests it on frames
  nobody has looked at is named in `docs/sam.md` with what has to hold: 131 images, $0.33, for
  Sean to start.
- The box's size is a typed number. For another game it has to come from that game (#259).
- A change that moves the player a little leaves the pairs silent; the fallback is not built.
- Still a probe. No verdict reads any of it.

## Files
`agents/anchor_rule.py`, `tests/test_anchor_rule.py`,
`tests/data/sam-anchor/bundled-box-48x68-traversal-seeded.json`, `docs/sam.md`
