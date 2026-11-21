# Measure the bundled gun's cooldown contract gap (#727)

## What changed

Recorded how the bundled gun's shot events and the gate's geometry assertions respond to the
same two-input probe. Added the measured result to the family coverage table for Q1–Q3.

## What was run

- Pinned Godot 4.7.2 on `305cefd`. All 12 headless replays completed 132 ticks. The clean and
  comment-only builds spawned twice and passed the advisory trace check 3/3 each. The public
  long-cooldown patch spawned once, and the standard never-made control spawned zero times.
  Both failed the advisory check 3/3 with complete traces.
- The local player-visibility check passed all 12 runs with 46 frames judged each. The
  test-spec schema refused the trace event-count operation. The gate reader refused both
  ways of supplying the advisory check as a gate file.
- The documented command reproduced all 12 outcomes. Verified 14 documentation links and
  fetched the required historic commit. The full `python3 -m unittest discover -s tests -t .`
  suite passed with 5,896 tests reported and 84 skipped.

## Not done

The measurement is advisory engine evidence without Bubblewrap isolation. A direct gate
assertion for projectile counts or intervals needs a contract decision before a draft can
be qualified.

## Files

- [Cooldown measurement and command](../measurements/727-cooldown.md)
- [Family coverage](../measurements/721-family-coverage.md)
- This work-log entry.
