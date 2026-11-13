# The outside trial shows the frames a check could not judge

## What changed

`tools/outside_trial.py`: when a check could not be decided because an object was not found
("... not found in 5 frames (first 38)"), the trial prints what the engine logged around that
first frame (three frames before, six after), as it already did for a failing check's first frame.
Each printed row now carries `groundFrom` and the player's `body` box as well (#388, #369).

Why: after #388, kinematic-character is needs-review only because 5 frames from frame 38 have no
ground under the player, and nothing showed what happens there. A check written for this game has to
be designed from those rows, not guessed.

## What was run

- `tests.test_outside_trial`: 20 tests, OK. New: a needs-review reason naming "first 38" makes the
  trial show ticks 70 to 88 of that route's head trace, ground and its source included.
- The existing test of the printed row now expects the two new keys (`groundFrom`, `body`; `None`
  where the trace has none).
- Full suite on this branch: OK (27 skipped).

## Not done

- The rows themselves come from the workflow's run on the pull request.
- The check for kinematic-character, which waits on them.

## Files

- `tools/outside_trial.py`, `tests/test_outside_trial.py`, `docs/new-work/2026-11-13-trial-shows-unjudged-frames.md`
