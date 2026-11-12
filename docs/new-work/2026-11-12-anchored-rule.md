# The anchored rule, offline: the probe's boxes held against a clean run's range (#330)

## What changed
Sean agreed the rule on November 12 after reading the first live runs: one box holding the point,
its size and its reach inside the range a clean run sets, confidence left out.

- `agents/anchor_rule.py`, new: `calibrate` sets the four ranges (width, height, reach above,
  reach below, in game pixels) from a clean run of an `anchor.json`, widened by a pad; `judge`
  holds every asked frame of a run against them. Fail on the first frame out; a frame with no
  answer is never a pass; nothing judged is needs-review. It sends nothing and no verdict reads it.
- `tests/data/sam-anchor/`: what SAM answered on the bundled game and its eight seeded bugs in runs
  43306507436 (point at the origin) and 43310237299 (14 px higher), taken from the
  `sam-probe-results` branch with the overlay paths left out. Numbers only, of our own game.
- `.github/workflows/sam-probe.yml`, probe mode with `anchor`: a new input `clean_routes` replays
  the clean game on other routes before SAM is asked, and the rule's table is made after the probe.
  No secret, environment or permission is added. The replay step holds no key.
- `docs/sam.md`: the rule, what it says on the recorded answers, and how to get the number that
  is missing.

## What was run
- `python3 -m unittest tests.test_anchor_rule`: 24 tests, OK. Six of them are over the recorded
  answers.
- The rule over the recorded answers for pads 0, 2, 4, 6, 8, set on clean and set on
  missing-texture v1: sinking v2 is out in 13 of 13 frames in every case; layering in 9 of 13 up to
  pad 4 and 7 of 13 from pad 6; clean set on missing-texture v1 has 1 frame out at pad 0 and none
  from pad 2.
- `python3 -m harness.run --route harness/routes/{coins,combat,traversal}.json` (Godot 4.7.2): 121,
  91 and 181 frames. The probe's `--dry-run` over the twelve runs at `--lift 14`: 131 requests. No
  frame of the three other clean routes has the player outside the picture.
- The workflow file parses, with 14 inputs. `python3 -m tools.merge_guard`: nothing to report.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2384 tests, OK, 26 skipped.
- **Not run: the workflow itself.** The replay step and the rule's step have not run on a runner.

## Not done
- **The false-alarm number.** No clean route the range was not set on has been asked about. That
  is one run for Sean to start (131 images, $0.33).
- The pad is 2 px from one comparison of two runs. It is not tuned and not held out.
- A pass can rest on 2 judged frames (fall-through). The rule says how many it judged; nothing
  yet says how many is enough.
- The point is still chosen by hand (`lift` 14 for this robot). The harness does not log the
  middle of the player's collision body.
- No calibration record with a contract (#330's step 4). Nothing but this tool reads the range, so
  it is a plain JSON beside the report until something else does.
- With twelve runs the step prints more than the ten notices GitHub keeps; the full numbers are in
  the files on the results branch.

## Files
`agents/anchor_rule.py`, `tests/test_anchor_rule.py`, `tests/data/sam-anchor/bundled-lift-0.json`,
`tests/data/sam-anchor/bundled-lift-14.json`, `.github/workflows/sam-probe.yml`, `docs/sam.md`
