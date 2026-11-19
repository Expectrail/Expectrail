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

## What the config changes

The hosted `seeded-bugs` job on the first head showed one change. `sinking_v2` moves only the player's drawing. With the player's texture bound, the trace carries the drawn box, so the engine record now catches it (`fail`), where before only the visual observer could. Sean accepted this on November 19: the engine doing better is fine. What matters is that the bundled game shows the setup a real user would have. The calibration step in `.github/workflows/ci.yml` now expects `sinking_v2: fail`. #658's parity run had covered only the clean routes and the Run it samples, not the seeded bugs.

## A bug this exposed in the trusted job

The hosted `release-gate` job then failed five tests with "the project config differs from the base's". This was a real bug, not an effect of the sample: the trusted job (`tools.ci_bundle.judge`) gives the gate a head game folder that is a name for the saved replays and not a folder on disk, so the head's config always read as absent. Any game with a project config, which is every onboarded game, could never be accepted by the two-job gate. `run_gate` now takes `head_config_game`, and the trusted job passes the real head checkout, whose game tree it has already matched to the capture. The config is only compared, never used. Two offline tests in `tests/test_ci_gate.py` cover it: the same config on both sides is accepted (this failed before the fix), and a changed config is still needs-review.

A sixth `release-gate` failure was the import-cache control test. It poisons the verifier's own cache and expects the drawing to change. Reading `harness/run.py`, a game with a config is imported again on every replay, so the poisoned cache is no longer drawn from as it stands. The control now uses a copy of the game without the config, and a cache warmed from that copy. This cause is read from the code and not confirmed with Godot here.

## What was run

- `tests.test_project_config` and `tests.test_bundled_config`: OK. The Godot cases skip here, since there is no engine.
- The full suite, in 3 parts: OK.
- The export scan: 0 errors.

## Not done

- `tools/outside_vision.py` also gives the gate folders that are not on disk, for both sides, so that trial compares no project config. Not changed here.
- The parity tool was not re-run with Godot after this move, because there is no engine here. The hosted seeded-bugs and capture jobs, and the Run it smoke, are the real check that every bundled replay is unchanged with the config read from the game folder.

## Files

- `harness/godot/platformer.project.json` (removed)
- `tools/bundled_config_parity.py`
- `tests/test_bundled_config.py`
- `tests/test_project_config.py`
- `tests/test_init_inspect.py`
- `tests/test_onboard.py`
- `docs/project-config.md`
- `.github/workflows/ci.yml` (the sinking calibration expectation)
- `expectrail/gate/verify.py`, `tools/ci_bundle.py` (the head's config in the trusted job)
- `tests/test_ci_gate.py`, `tests/release_gate/gate_interference.py`
- `docs/new-work/2026-11-19-bundled-config-beside-game.md`
