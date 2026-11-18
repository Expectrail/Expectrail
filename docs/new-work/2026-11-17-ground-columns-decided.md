# The ground's columns: Sean's decision written down as the rule (#354)

## What changed
Gap 2 of #354 (whose collision sets the gate's ground columns when a change resizes the player) was
decided by Sean on November 14, 2026: the candidate's own collision, as the harness already does.
`docs/harness.md` still called it "Not decided (#354, for Sean)". It now states the decision, Sean's
reason (a legitimate resize must be read under what the changed game stands on; the visual observer,
which judges the drawn sprite, covers a fake fix that shrinks the collision box), and keeps the
base-commit design as the one not taken. `NarrowedRobotOnSlopeTest`'s docstring and comment say
"decided rule" in place of "open choice"; none of its assertions changed. A new engine-free test,
`DecisionRecordedTest`, checks that the doc records the decision and the test that holds it, and that
neither the doc section nor the test file still calls it open. No harness or trace change.

## What was run
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_ground_under` with Godot
  4.7.2-stable (from `harness/get_godot.sh`, SHA-512 checked): 40 tests, OK, none skipped.
  `NarrowedRobotOnSlopeTest` ran with the real engine.
- Full suite on this branch from main at 3b42a95: see the pull request description.

## Not done
Nothing left on #354 for a builder: gaps 1 and 3 merged in #464 and #480, gap 2 is this record.

## Files
- `docs/harness.md`
- `tests/test_ground_under.py`
- `docs/new-work/2026-11-17-ground-columns-decided.md`
