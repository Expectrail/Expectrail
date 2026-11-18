# `expectrail inspect --at-tick N`: the bound objects at one tick of a replay (#260)

## What changed

`expectrail inspect GAME --at-tick N [--route ROUTE] [--json]` replays the project headless with its
own `expectrail.project.json`, along the config's first route or the route given, and reports each
bound object at physics tick N: its node path (and, for a respawn, which node at that path), its box
in captured-frame pixels, its box in world units, the engine's visible flag, whether the box overlaps
the frame, and whether the box is the drawing's or the collision shape's. It reads the `roleObjects`
that every configured replay already records (#538); it adds no engine code.

- Contract: `contracts/inspection.v1.schema.json` (`expectrail.inspection/v1`), the example
  `contracts/examples/inspection.json` (the real output for config-lane at tick 60), the writer
  `expectrail.inspection.document` and the reader `expectrail.inspection.problems`, which recomputes
  `onScreen`, the tick range and the measured/absent lists instead of taking the record's word.
- A bound role with no object at that tick is listed as absent, never given a box.
- Refused with what to change, and no measurement printed: no `project.godot`, no config (names
  `expectrail init`), no route (names `--route` and `expectrail route --auto`), a config route that is
  missing or a link out of the project, a tick past the route (before any replay) or past the recorded
  rows, a trace without role boxes or with a row it cannot read ("cannot tell"), a replay failure (the
  harness's reason, for example a binding never found, without a pointer into the removed replay
  folder), and a config edited during the replay. `--route` without `--at-tick` is a usage error.
- Without `--at-tick`, `inspect` is unchanged: it reads saved scenes and starts nothing.
- `docs/project-config.md` gains "See the bound objects at one tick"; the command list names the
  option; the wheel carries the new module.

## What was run

- `python3 -m unittest tests.test_inspect_at_tick`: 26 tests, OK, including three that replay in
  Godot 4.7.2 (sandbox off): config-lane at ticks 0 and 90 and crate-run at tick 60 match a direct
  `harness.run` replay of the same route value for value, the player moves right as the route holds
  `move_right`, and a group binding the replay never finds is refused naming `bindings.coin`.
- Four mutations of `expectrail/inspection.py` (on-screen always true, every role absent, the reader's
  measured-and-absent check off, the route-length check off) were each caught by the offline tests.
- By hand on a copy of config-lane: `expectrail inspect GAME --at-tick 60` printed the player at
  `Actors/Avatar`, box 168,108 to 192,132 px in a 360 x 240 frame. The camera follows the player, so the
  box is centred on the frame (180, 120), which is what a hand check expects.
- Full suite on the branch (main at 49226b6): `python3 -m unittest discover -s tests -t .`, 4,824 tests, OK, 34 skipped.

## Not done

- `init --dry-run` to a reviewed, approved verification on the bundled game and the second test
  project (the Done-when line), and the bundled game's own config: `--at-tick` needs a config, and the
  bundled game has none (#259).
- Runtime discovery for `init` (objects spawned at runtime are not in saved scenes).
- `calibrate` stays with #330 by the scope note on #260.
- Not looked at in a browser: this is a command, not a page.

## Files

- `contracts/inspection.v1.schema.json`, `contracts/examples/inspection.json`
- `expectrail/inspection.py`, `expectrail/onboarding.py`, `expectrail/cli.py`, `setup.py`
- `tests/test_inspect_at_tick.py`
- `docs/project-config.md`
