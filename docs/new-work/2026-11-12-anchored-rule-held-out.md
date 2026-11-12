# The anchored rule against clean routes it was not set on: one false alarm, written down (#330)

## What changed
Nothing in the rule. Its first measurement on clean frames the range was not set on is recorded,
and the fault it found is held by a test so that it stays in view until the rule changes.

- `tests/data/sam-anchor/bundled-lift-14-other-clean-routes.json`: SAM's answers on the clean game
  replayed on `coins`, `combat` and `traversal` (run 43316420400, started by Sean), taken from the
  `sam-probe-results` branch with the overlay paths left out.
- `tests/test_anchor_rule.py`: two tests over those answers.
- `docs/sam.md`: the result and what to try next.

## What was run
- Run 43316420400 is Sean's: 131 images, $0.33 counted. I read `anchor.json` and `anchor-rule.md`
  from the results branch and looked at frame 20 of the traversal contact sheet.
- The rule over the recorded answers, set on the smoke route's clean run: at pad 2, coins 0 of 13
  out, combat 0 of 10, traversal 1 of 13 (frame 20). At pad 0: 4, 1 and 3 out. The traversal frame
  stays out up to pad 43; at pad 44 it is in and sinking v2 passes.
- The nine earlier runs in this run against `bundled-lift-14.json`: 95 of 95 answers the same.
- `python3 -m unittest tests.test_anchor_rule`: 28 tests, OK.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, main at aa290b1: 2420 tests, OK, 26 skipped.

## Not done
- The rule is not changed. What to try is asking about the frames either side of a frame that is
  out, and that needs one measurement first: how many frames the robot-and-trunk answer lasts.
- 36 frames on three routes is a small sample. One false alarm in it is not a rate to quote.

## Files
`tests/data/sam-anchor/bundled-lift-14-other-clean-routes.json`, `tests/test_anchor_rule.py`,
`docs/sam.md`
