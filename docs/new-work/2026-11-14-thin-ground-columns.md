# Read the ground at both ends of a thin body (#354)

## What changed

For a collision span up to and including 2.5 px, the harness samples the left end,
midpoint and right end. A ledge under one end now counts even when the midpoint
is over air. Wider bodies keep the 1.25 px inset. The two Python observation
readers project the height logged by the engine and preserve a gap.

## What was run

- Before the fix, the new Godot regression failed for 1 and 2.5 px at both sides
  of the gap. The 2.75 px control passed.
- With the pinned Godot and `EXPECTRAIL_ENGINE_TESTS=required`,
  `python3 -m unittest -v tests.test_ground_under` passed all 37 tests. The new
  test crosses both sides of a gap and a step, and checks the measured uphill
  height on a slope.
- `python3 -m unittest -v tests.test_ground_under.GroundReaderTest tests.test_engine_check`
  passed all 12 tests.
- `python3 -m tests.compare_ground_traces` compared fresh headless recordings
  from main and the changed harness. The complete trace bytes matched on the
  bundled smoke, coins, combat, traversal and slope routes. With `--kinematic`
  and the pinned kinematic-character game, its 360-row walk also matched byte
  for byte (96,438 bytes). Both outside replays required Bubblewrap and recorded
  a confined filesystem and no network. Both Python readers gave the same
  output on main and the changed code for all six recordings.
- Full suite: `python3 -m unittest discover -s tests -t .` ran 3,543 tests on
  main and 3,544 after the change. Both ended OK with 51 skips and no failures
  or errors. The separate Godot-required run above had no skips.

## Not done

Sean still decides whose collision sets the gate's columns when a change resizes
the player. This slice measures the candidate's collision, as main does. The
fix-loop verifier keeps its independent reference. No frames were rendered.

## Files

- `harness/godot/expectrail_harness.gd`
- `agents/observations.py`
- `tests/test_ground_under.py`
- `tests/compare_ground_traces.py`
- `docs/harness.md`
- `docs/new-work/2026-11-14-thin-ground-columns.md`
