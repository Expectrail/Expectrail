# Mirror-inputs metamorphic checks measured on an outside game, kinematic-character (#675)

## What changed

- `tools/metamorphic_outside.py` measures the mirror-inputs metamorphic checks (#675, piece 3) on a game the
  team did not write: `kinematic-character` from the outside list, fetched at its pinned commit and never
  copied here. The project's own `project.godot` input map is the action catalog. Each route is replayed
  3 times as pinned, 3 times on the player's do-nothing control (made from the project's `Player` scene by
  `expectrail/jit/do_nothing.py`), and once on each change the outside list declares (`broken` is a defect;
  `harmless` and `invisible` leave the player's motion as it was, so a check failing on them is a false
  reject). It also adds a seeded direction-dependent fault, made at run time as a patch and never committed
  against the project: an autoload that pushes the player 1 px back to the right on each tick `move_left` is
  held (`drag-left`). Every replay runs in the required sandbox.
- A job `metamorphic-outside` in `outside-trial.yml` runs it on pull requests that touch it. No secret, no
  `environment:`, no wider permissions, no model. It fails only when the measurement could not be made.
- `tools/metamorphic_public.py`: `replay_all` passes a `sandbox` mode to the harness when given one.
- `.gitignore`: `tools/metamorphic_public.py` and `tools/metamorphic_outside.py` are listed as kept.

Advisory: nothing here changes what the generator offers, what may count or what may clear a change.

## What was run

- `python3 -m unittest tests.test_metamorphic_outside`: 16 tests, OK.
- A rehearsal of the tool's measurement on the bundled game standing in for the outside project (local,
  Godot 4.7.2, sandbox off, no declared changes, only the seeded fault): 14 pairs, 56 checks, 196 replays,
  none failed. 28 pass 3 of 3 as pinned; all 28 are "not exercised" on the do-nothing control, so all 28 are
  kept. `drag-left` is caught by the 14 sideways-travel checks and by none of the equal-signal checks.
  405 seconds on 2 CPUs.
- Full suite on main 0822f1a merged with this change, with the engine present: 5,815 tests, OK, 44 skipped.
- The outside run on kinematic-character, in the `metamorphic-outside` job of run 44788077524 (pull request
  #719, head b22aaa8, conclusion success). Of 44 checks, 22 pass 3 of 3 as pinned, and none passes the
  do-nothing control, so 22 are kept. The 11 sideways-travel checks catch `drag-left`. None catches
  `broken`, and none fails `harmless` or `invisible`. 220 replays, all in the sandbox, none failed. Published
  in `docs/measurements/675-metamorphic-outside.md` and `docs/outside-projects.md`.

## After Sean's review on #719

- `tools/metamorphic_outside.py` prints a section "What these counts can and cannot say", computed from the
  rows: that a mirror check sees only direction-dependent faults, how many checks are not exercised on any
  build and on which signals, how many kept checks the do-nothing control could not judge, and that the
  seeded fault was written for the measurement. Two tests cover it (it appears when it applies, and the
  never-exercised line stays out when nothing is never exercised).
- The section is added to `docs/measurements/675-metamorphic-outside.md` from the published counts (22 of 44
  never exercised, on `max_rise_px` and `air_jumps`; 22 of 22 kept checks indeterminate on the control;
  `drag-left` seeded here), with a reading of the bundled game's "1 of 24"; a one-paragraph note points to it
  from `docs/measurements/675-metamorphic-mirror.md`. The CI artifact with the rows could not be fetched from
  this session, so the section was written by hand from the counts in the published table and checked by
  running `limits()` on rows parsed from that table: the output matches.
- The generator finding is issue #728.
- `python3 -m unittest tests.test_metamorphic_outside`: 18 tests, OK.

## Not done

- Turning on `--metamorphic` in `jit.yml`.
- Re-running the public counting audit (the last item of #675's `Done when`).

## Files

- `tools/metamorphic_outside.py` (new)
- `tests/test_metamorphic_outside.py` (new)
- `tools/metamorphic_public.py`
- `.github/workflows/outside-trial.yml`
- `.gitignore`
- `docs/measurements/675-metamorphic-outside.md` (new)
- `docs/outside-projects.md`
- `docs/measurements/675-metamorphic-mirror.md`
- `docs/new-work/2026-11-20-metamorphic-outside.md` (new)
