# The bundled game's proposed config, held to today's results (#259)

## What changed

#259 asks that the bundled game get an `expectrail.project.json` that reproduces today's results
exactly. Agents do not edit `game/platformer`, so the config is kept outside it and checked on copies.

- `harness/godot/platformer.project.json` holds what `expectrail init` proposes for the bundled game:
  - the entry scene `res://game_singleplayer.tscn`;
  - the viewport 800 × 480;
  - 120 physics ticks a second, and capture at 60;
  - the game's 15 input actions;
  - the player bound to `Level/Player`, drawn with `res://player/robot.webp`.

  It leaves out init's `draft` flag and its draft route. Coins, enemies and bullets are not bound:
  they have a class but no group, and a binding names a node or a group.
- `python3 -m tools.bundled_config_parity [--out FILE] [--traces-only]` compares copies of the game
  with and without the config beside `project.godot`:
  - Every field init proposes must be what init reads from the game (`declared_mismatches`).
  - Each public route (smoke, combat, coins, traversal) is replayed headless both ways. A configured
    trace may only add what a config adds: `roleObjects` per row, `bindings`, the measured window
    `viewport` and `capabilities.roleBoxes`. Anything else that differs is reported. The tool also
    checks that the config was applied at all, so an unapplied config cannot pass as parity.
  - The three Run it samples (clean, fall-through-bug, fall-through-repair) run through the real job,
    gate and both observers. The recorded vision answers are keyed by each frame's exact bytes, so
    equal answered counts mean the frames were the same. Every replay of the configured runs must
    show the config was used.

  It exits 0 when every case is the same, 1 when anything differs, and 5 ("cannot tell") when it
  could not run, for example with no engine.
- `docs/project-config.md` says where the config is, what the check compares, and one gap I found.
  The replay never compares a config's `viewport` or tick rate with `project.godot`. With
  `viewport` set to 640 × 360, the replay and the clean decision were unchanged, and no one was
  told. That is filed as #657. The parity check holds the bundled config to init's values in the
  meantime.
- `.gitignore` lets the new tool in (`/tools/*` is ignored by default).

## What was run

All of this was on this machine: Godot 4.7.2, sandbox off, no model called, no workflow dispatched.

- `python3 -m tools.bundled_config_parity --out parity.json`, exit 0 (5 min):
  ```
  declared settings: as init reads them from the game
  trace smoke: same (240 rows, config applied: True)
  trace combat: same (180 rows, config applied: True)
  trace coins: same (240 rows, config applied: True)
  trace traversal: same (360 rows, config applied: True)
  sample clean: same (accept, 120/120 recorded answers, config used in 1 of 1 replays)
  sample fall-through-bug: same (reject, 135/135 recorded answers, config used in 2 of 2 replays)
  sample fall-through-repair: same (accept, 135/135 recorded answers, config used in 2 of 2 replays)
  parity: every case is the same
  ```
  The unconfigured smoke trace's SHA-256 is `3ae192de…`, the value recorded on main in
  `2026-11-16-role-boxes.md`. An earlier run with the player bound by its short name `Player` gave
  the same result. The config now uses init's full path.
- A captured smoke replay with the config: 120 frames at 1600 × 960. The trace's `viewport` is the
  window size (`[1600, 960]` with frames, `[800, 480]` headless), not the config's value.
- `tests.test_bundled_config`: 15 tests, OK (85 s). 13 are offline. 2 are in Godot: the smoke trace
  and the clean sample are the same with the config, and a wrong texture leaves the replay unchanged.
  That second one is why the declared-settings check exists. The Godot tests skip, naming the
  missing engine, display or `patch`, and fail instead under `EXPECTRAIL_ENGINE_TESTS=required`.
- Five mutations of the tool were each caught by the offline tests:
  - no row comparison;
  - "config applied" always true;
  - the viewport not compared;
  - `equal` ignoring declared mismatches;
  - capabilities allowed to gain anything.
- Full suite on the branch from main at 8c2f9a2 (`python3 -m unittest discover -s tests -t .`):
  5,302 tests, OK, 41 skipped. The first run had 1 failure and 3 errors in
  `tests.test_replay_sandbox.HarnessTest`. The cause was my exit-5 test: it called the tool's `main`,
  which set `EXPECTRAIL_SANDBOX=off` for the rest of the process. That test now keeps the environment
  to itself, and the second run is the one above. No existing test was changed.

## Not done

- The config is not beside `project.godot`. That is an edit to `game/platformer`, so it is Sean's.
  If he puts it there, the unconfigured path stops being what the bundled game runs, and
  `tests.test_project_config.ReaderTest.test_the_crate_loads_and_the_bundled_game_has_no_config`
  must change with it.
- Rendered parity was measured through the recorded answers on the three Run it routes only. The
  combat, coins and traversal routes were compared headless, without frames.
- #657, comparing a config's declared settings with the game, is not built.
- Not looked at in a browser: this is a file and a command, not a page.

## Files

- `harness/godot/platformer.project.json`
- `tools/bundled_config_parity.py`
- `tests/test_bundled_config.py`
- `docs/project-config.md`
- `.gitignore`
- `docs/new-work/2026-11-19-bundled-config.md`
