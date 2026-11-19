# The bundled game's config sits beside its project.godot (#259)

## What changed

Sean decided on November 19, 2026 that the bundled game's `expectrail.project.json` lives where it would for any game, beside `project.godot`. He committed `game/platformer/expectrail.project.json`, byte-identical to the config #658 proposed. Agents do not edit `game/platformer`.

The follow-up in this pull request:
- removes the old copy at `harness/godot/platformer.project.json`;
- points `tools/bundled_config_parity` at the new file. The unconfigured side now removes the file from its copies of the game (`_without_config`), instead of the configured side adding one.
- updates the two tests that asserted the bundled game had no config;
- makes the init and onboarding tests, which copy the bundled game as a game not yet onboarded, leave its config out of the copy (`tests/test_init_inspect.py`, `tests/test_onboard.py`). Without that, 13 tests saw an already-onboarded game.
- updates `docs/project-config.md`.

Every replay of the bundled game now reads this config. #658's parity run (Godot 4.7.2) showed that it changes nothing the replays or decisions depend on:
- four public routes gave the same traces, apart from the role boxes, bindings and window size a config adds;
- three Run it samples gave the same decisions, with every recorded vision answer still matched by exact frame bytes.

## What was run

- `tests.test_project_config` and `tests.test_bundled_config`: OK. The Godot cases skip here, since there is no engine.
- The full suite, in 3 parts: OK.
- The export scan: 0 errors.

## Not done

- The parity tool was not re-run with Godot after this move, because there is no engine here. The hosted seeded-bugs and capture jobs, and the Run it smoke, are the real check that every bundled replay is unchanged with the config read from the game folder.

## Files

- `harness/godot/platformer.project.json` (removed)
- `tools/bundled_config_parity.py`
- `tests/test_bundled_config.py`
- `tests/test_project_config.py`
- `tests/test_init_inspect.py`
- `tests/test_onboard.py`
- `docs/project-config.md`
- `docs/new-work/2026-11-19-bundled-config-beside-game.md`
