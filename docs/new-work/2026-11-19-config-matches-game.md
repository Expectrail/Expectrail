# A config whose viewport or tick rate is not the game's own is refused before any replay (#657)

## What changed
`expectrail.project/v1` requires `viewport` and `physicsTicksPerSecond`, but nothing compared them
with the game's `project.godot`, so a wrong value stayed in the config and nobody was told.

- `expectrail.godot_project.declared_settings` reads the game's logical viewport
  (`display/window/size/viewport_width` and `viewport_height`, default 1152 by 648) and its tick
  rate (`physics/common/physics_ticks_per_second`, default 60). A value that is present and not a
  whole number in range, a key set twice, or an unreadable `project.godot` is refused, never
  replaced by the default. Feature overrides (`viewport_width.mobile`) and the same key in another
  section are not the setting.
- `require_declared_settings` refuses a Godot config that differs, naming the field and both
  values. `harness/run.py` calls it before the import (on the game, with the config beside it or
  the base's config) and again on the copy with the change under test applied; there the message
  says the change moved the setting. A Unity config is not compared with a Godot file.
- `expectrail inspect` now reads the viewport through the same function, so what `init` proposes
  and what the replay checks cannot drift apart.
- `docs/project-config.md` says what the config's `viewport` means (the logical viewport) and what
  a trace's `viewport` means (the measured window, which can be larger with a window override).

## What was run
- `python3 -m unittest tests.test_project_settings_match`: 20 tests, OK. They cover each mismatch,
  both together, one axis off, a default the config contradicts, six unreadable values, a key set
  twice, a feature override, a missing `project.godot`, a Unity config, inspect reading the same
  values, every checked-in config with a game here (`tests/projects/crate-run`,
  `tests/projects/config-lane`, `contracts/examples/project.json`), and the replay: a disagreeing
  config beside the game and a disagreeing base config start nothing, a patch that moves the
  game's viewport is refused on the copy, and a matching config still replays.
- Five mutations were each caught: no check on the game, no check on the copy, no viewport
  comparison, duplicates allowed, section ignored.
- The related modules (`test_project_config`, `test_onboard`, `test_onboard_review`,
  `test_second_project`, `test_app_projects`, `test_trial_stops`, `test_project_audit`) with the new module: 99 tests,
  OK, 3 skipped.
- The full suite on the branch from main at 8c2f9a2: 5,218 tests, OK, 66 skipped.
- Not run against the pinned outside games (they are fetched, not vendored). The Breakout trial's
  recorded headless trace (`docs/outside-trials/breakout/evidence/harmless/trace.json`) has
  viewport 360 by 640 at 60 ticks, which is what its config declares. The bundled game declares
  800 by 480 at 120 ticks, which is what #658's config says.

## Not done
- No Godot replay was started for this change; the tests stop before the engine.

## Files
- `expectrail/godot_project.py`
- `harness/run.py`
- `expectrail/onboarding.py`
- `docs/project-config.md`
- `tests/test_project_settings_match.py`
- `docs/new-work/2026-11-19-config-matches-game.md`
