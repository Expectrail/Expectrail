# A game with no ground is needs-review, not a reject against a guess (#346)

## What changed
The first run on games the team did not write rejected Godot's Dodge the Creeps, unchanged:
"player is 450px past the boundary (above 0, tolerance 20)". The game has no ground. The engine's
position log had no ground line in any row, and `agents.observations.from_trace_synthetic` took such
a trace for one from before the harness logged the ground, and gave it a floor guessed from the
player's own positions (the first position, or 0, when the player is never on a floor).

- A row with no ground line now gives no ground observation. The check against the ground cannot
  be decided there and is needs-review ("a missing object is never a pass").
- The fallback to a floor taken from the player is kept for old traces only: those with no camera
  rows either. Today's harness logs the camera in every row.
- The observations say "not measured: no tile collision under the player" where they said "level
  tile geometry".

## What was run
- Our own tile-less test project (`tests/projects/event-input`) with the bundled approved spec, the
  real engine (Godot 4.7.2), `expectrail verify`: main's code says reject (exit 1, "1 of 1 public
  checks fail after the change"); this change says needs-review (exit 2, "1 of 1 public checks
  could not be decided").
- `tests.test_sam.EngineGroundTest`: a top-down trace shaped like Dodge the Creeps is needs-review;
  a level with ground in some places and none in others is needs-review when nothing fails and
  still fail when the player sinks where the ground is measured.
- The real sample: accept, reject, accept, each as expected.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2237 tests, OK, 26 skipped.
- One existing assertion changed: the test of an older trace removed the ground line and left the
  camera rows in, which no older trace has. It now removes both, and still holds what it held.

## Not done
- Dodge the Creeps itself was not run again by me; the trial's next run (#345) will show it.
- Not run here: `harness.check_seeded` (every seeded bug against the clean game); CI's
  `seeded-bugs` job runs it.
- The platformer in the same trial is rejected for another reason (its ground line is measured and
  wrong for that level). Not touched here.
- The SAM path (`from_trace(..., provider="sam")`) was not changed.

## Files
`agents/observations.py`, `tests/test_sam.py`
