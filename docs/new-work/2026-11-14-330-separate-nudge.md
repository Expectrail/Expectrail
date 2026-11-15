# Ask the nudged point in its own request (#330)

## What changed

- The second live calibration on kinematic-character (run 43643679280, $0.0475, 19 images) found
  the player at its place in 19 of 19 frames with the right size in 19 of 19, but the nudged point
  gave the same answer in 0 of 19. Both points were asked in one request as two objects. A
  segmentation model gives each pixel to one object, so the second point on the same sprite came back
  without it, in every frame.
- `expectrail/anchored.py`: the calibration asks the point and the nudged point in two requests.
  The rules are unchanged.
- `tests/test_anchored_observer.py`: a stand-in that behaves that way (`OneOwner`: only the first of
  several points in one request gets the sprite) is now enabled; it is refused on main. The count of
  requests in a calibration is 26 for 13 frames.
- `docs/outside-projects.md`: the second live calibration.

## What was run

- `tests.test_anchored_observer` and `tests.test_outside_vision`: 28 tests, OK. The new test fails
  on main.
- `python3 -m unittest discover -s tests -t .`: 3,575 tests, OK (31 skipped).

## Not done

- Confirming the cause from the run's per-frame rows (the artifact), and the third live run.

## Files

- `expectrail/anchored.py`
- `tests/test_anchored_observer.py`
- `docs/outside-projects.md`
- `docs/new-work/2026-11-14-330-separate-nudge.md`
