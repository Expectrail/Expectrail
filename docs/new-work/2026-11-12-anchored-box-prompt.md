# The pairs' first real test, written down, and a box as the prompt (#330)

## What changed
- **The pairs failed their test and it is recorded.** Run 43326853189 (Sean's): on the traversal
  route the slip the pairs were built for cancels (frame 20: 107.5 px tall in the clean game, 106.5
  in the harmless change), and frame 100 is a new false alarm (the robot touching an enemy: robot
  alone in one game, robot and enemy as one object in the other). The answers are saved as
  `tests/data/sam-anchor/bundled-lift-14-traversal-seeded.json` and a test holds the fault in view.
- **A box as the prompt.** `agents/sam_observations.py`: `box_prompt` and
  `MetaSamClient.segment_in`, through the same sender and spend cap as every image.
  `agents/sam_anchor.py --box WxH`: a box of that size in game pixels centred on the point, cut to
  the picture; each row gains the box that was asked about, how much of the answer lies inside it
  and how much of it the answer fills; the report says which question was asked.
- `agents/anchor_rule.py` refuses to compare answers to a point with answers to a box, or to boxes
  of two sizes.
- `.github/workflows/sam-probe.yml`, probe mode with `anchor`: input `box`. No secret, environment
  or permission is added.
- `docs/sam.md`: the traversal result, the box, and what could go wrong with it.

## What was run
- Run 43326853189 is Sean's: 52 images, $0.13 counted. I read `anchor.json` and `anchor-pairs.md`
  from the results branch and looked at frame 100 of three contact sheets.
- `python3 -m unittest tests.test_anchor_rule tests.test_sam_anchor`: 96 tests, OK.
- The box on real frames with a stand-in answer (the traversal runs rendered here with Godot
  4.7.2): at `--lift 17 --box 48x68` it frames the robot on clean frames 0 and 100 and leaves the
  enemy of frame 100 mostly outside; on sinking v2 the robot hangs out of the bottom of it.
- Every shell step of the probe job passes `bash -n`; the workflow parses with 16 inputs;
  `python3 -m tools.merge_guard`: nothing to report.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, main at 40b3939: 2565 tests, OK, 27 skipped.
- **Not run: a box against the service.** What SAM answers to a box is not known: whether it comes
  with a confidence, what comes back when the box holds only scenery, and what it costs.

## Not done
- The measurement. One run for Sean (52 images, $0.13): `anchor` ticked, `lift` 17, `box` 48x68,
  `route` traversal, `runs` clean,missing-texture_v1,layering_v1,sinking_v2.
- If a box steadies the clean answers and still tells the bugs apart, the size has to come from
  the game and not from a typed number (#259).
- The outside probe workflow has no `box` input yet.
- Still a probe. No verdict reads any of it.

## Files
`agents/sam_observations.py`, `agents/sam_anchor.py`, `agents/anchor_rule.py`,
`tests/test_sam_anchor.py`, `tests/test_anchor_rule.py`,
`tests/data/sam-anchor/bundled-lift-14-traversal-seeded.json`, `.github/workflows/sam-probe.yml`,
`docs/sam.md`
