# The outside trial finds the unjudged frame where the gate writes it

## What changed

#393 merged in its first version: it looked for "not found in N frames (first F)" only in the
decision's reasons. The gate puts that text in the finding's reason, so the trial run on #393 printed
nothing for kinematic-character's frame 38. `tools/outside_trial.py` now reads the findings as well,
and the test writes the reasons as the gate does (a general decision reason, the specifics in the
finding).

## What was run

- `tests.test_outside_trial`: 20 tests, OK.
- Full suite on this branch: OK (27 skipped).
- The trial run on this pull request prints the frames.

## Not done

- Reading the frames, and the check for kinematic-character that follows from them.

## Files

- `tools/outside_trial.py`, `tests/test_outside_trial.py`, `docs/new-work/2026-11-13-trial-unjudged-frames-fix.md`
