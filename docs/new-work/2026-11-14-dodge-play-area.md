# Give Dodge the Creeps a play-area check

## What changed

The outside trial copies the spec named by a project. Kinematic-character still uses the bundled
ground check. Dodge gets a draft that checks whether its recorded player origin stays in the play
area. The broken patch removes the clamp. The harmless patch changes a comment.

## What was run

- `python3 -m unittest -v tests.test_dodge_check tests.test_outside_trial` ran 27 tests, OK.
  Synthetic Dodge traces passed on all four boundaries and failed one pixel outside each.
  A missing player gave needs-review. With stand-in replays and no vision, kinematic-character
  gave reject for broken and needs-review for harmless and invisible.
- `tools.dodge_play_area` read the pinned project's viewport. Its region matched the spec.
  The trial laid out the pinned source and both patched copies. The broken copy lacked the
  clamp and the harmless copy differed from the original only in its comment.

## Not done

A person must approve the Dodge spec. The PR's sandboxed outside trial still needs to run and its
per-change findings need to be read. No vision calibration or live model run was made.

## Files

- `tools/outside_trial.py`, `tools/dodge_play_area.py`
- `tests/outside/projects.json`, `tests/outside/specs/dodge-play-area.json`
- `tests/outside/dodge-the-creeps/changes/broken.patch`, `tests/outside/dodge-the-creeps/changes/harmless.patch`
- `tests/test_dodge_check.py`
- `docs/outside-projects.md`, `docs/new-work/2026-11-14-dodge-play-area.md`
