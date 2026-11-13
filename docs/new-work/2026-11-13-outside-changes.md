# The outside trial judges changes to a game we did not write

## What changed

The product manager's call 4: the first outside verdict that is not needs-review needs a broken
version of an outside game. `tools/outside_trial.py` now reads an optional `changes` list per
project in `tests/outside/projects.json`: a patch of ours under `tests/outside/<project>/changes/`,
what it does, and the verdict it should get. For each change the project as pinned is the base,
a patched copy is the head, and `expectrail verify --base` judges it. The table shows the expected
verdict beside the one given; a mismatch is a finding, not a failure of the trial.

kinematic-character gets two changes against `player/player.tscn`:
- `broken`: `collision_mask = 0` on the player, so it falls through the floor. Expected: reject.
- `harmless`: a tint on the player's sprite. Expected: needs-review, the same as the project
  unchanged, until a check written for this game is approved.

The list's reader refuses a patch outside the project's own `changes/` folder, a name used twice,
an expected verdict that is not one, and a change with no description. `git apply` refuses a patch
that reaches outside the project folder, and a patch that does not apply stops the trial.

## What was run

- Both patches were checked with `git apply --check` against the project's folder at the pinned
  commit `b761b4c` (read, never run, here).
- `python3 -m unittest tests.test_outside_trial`: 18 tests, OK. New: the change is applied to a copy
  and the project unchanged is the base (`--base` and `--head` checked on the command line given);
  a patch that does not apply stops the trial; a patch that climbs out is refused; the list's new
  refusals.
- The full suite on this branch: 2814 tests OK, 27 skipped.
- No outside project was started here. The real run is `outside-trial.yml` on this pull request.

## Not done

- The verdicts of the two changes: the workflow's run on the pull request records them.
- A check written for kinematic-character and approved by Sean, so the harmless change can be
  accepted. That waits for the traces this run produces.

## Files

- `tools/outside_trial.py`, `tests/test_outside_trial.py`, `tests/outside/projects.json`
- `tests/outside/kinematic-character/changes/broken.patch`, `tests/outside/kinematic-character/changes/harmless.patch`
- `docs/outside-projects.md`, `docs/new-work/2026-11-13-outside-changes.md`
