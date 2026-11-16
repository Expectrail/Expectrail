# The no-model sensor can judge pixel checks about the enemy (#286)

## What changed
The `visual-sensor` observer looked only for the player. A pixel check about the enemy could only be
judged by SAM, which costs money for each image. Now the sensor can also look for every enemy the
engine logs a box for, with no model and no charge.

- `agents/template_observations.py`:
  - `object_predictions(trace, frames, role)` reads each enemy's or bullet's logged box (`enemyBoxes`,
    `projectileBoxes`) through the next tick's camera, the same way `player_predictions` reads the
    player's. A trace that cannot say gives `None`, not a guess. That covers a trace with no
    `capabilities.objectBoxes`, no camera, or a malformed entry.
  - The one-object search moved into `look` and `matchers_for`, and `from_replay` now uses them. Its
    output has not changed, and the existing sensor tests pass unchanged.
- `agents/template_foreground.py`:
  - `calibrate_routes(..., objects=("enemy",))` crops, in each clean frame, the lowest-id enemy whose
    box is wholly on screen and touches no other object's box. Each crop is masked with the enemy's
    own approved art.
  - Each object's templates are de-duplicated against its own templates only, and crops too flat to
    identify a sprite are left out. The catalogue attaches to the objects it names (the player).
  - The threshold is still chosen on the player. The enemy's positives and negatives on the
    validation replay, counted at that threshold, go under `calibration.objects.enemy` with a status
    of its own (`met` or `unmet`).
  - The reader (`check_bank`) recomputes that status from the counts. It also refuses a record that
    claims templates the bank does not hold or more matches than it counted.
  - With no `objects`, the bank is as before: the same 408 player templates on the bundled game.
- Contracts: `contracts/template-bank.schema.json` and `contracts/observations.schema.json` gain the
  optional `calibration.objects`. There is a new synthetic example,
  `contracts/examples/template-bank-foreground-named.json`. The writer and the readers are in the same
  pull request.
- `expectrail/jit/template_observer.py`:
  - The run carries `objects.enemy`: one row for each planned frame and one entry for each box, the
    shape SAM's observer uses.
  - A box partly on screen is a gap. A box wholly off screen is counted in `outside`. More than
    `pixel.MAX_BOXES` on screen means that frame is not asked about. `player=False` is supported.
  - The enemy is refused, so its checks are not run, in three cases: the bank has no enemy template,
    its enemy calibration is not `met`, or it is not an approved-art bank.
  - `calibrate_bank` (jit.yml's `sensor-bank` job) now calibrates the enemy as well.
- `expectrail/jit/pixel.py`:
  - `OBSERVERS["visual-sensor"]["boxes"]` is now `("enemy",)`.
  - `named_observations` reads the sensor's `not-found` (`absent`) as an observation, not a gap, the
    way `observations` already did for the player.
- The bullet is not offered. Calibrated the same way on the bundled game, its 16 x 16 clean crops gave
  no template with enough opaque detail.
- Docs: `docs/jit.md` ("The enemy") and `docs/template-sensor.md`.

## What was run
- `python3 -m unittest tests.test_jit_sensor_named`: 19 new tests, OK. They cover calibration with
  the enemy, the reader's recomputation and forgeries, object predictions, the observer's rows and
  refusals, a missing enemy failing `visible`, partial and crowded frames as gaps, and the keep rule.
- On the real engine here (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb; no model, not in CI):
  - `python3 -m expectrail.jit.cli sensor-bank` replayed the four clean calibration routes. Its first
    two attempts stopped on two problems that this change then fixed: the catalogue wanted every
    object, and a flat enemy crop failed the whole calibration.
  - Calibration was then re-run, with this change, from those same clean replays (3 min 40 s). It gave
    408 player templates (as before) and 148 enemy templates, in a 34.8 MB bank. The player matched
    358 of 360 positives and 0 of 360 negatives. The enemy matched 251 of 251 positives and 0 of 251
    negatives (`met`). The bullet had 0 templates.
  - Judged with that bank on three library probes, on the clean game, `enemy-walks-backwards` and
    `enemy-slides-when-shot`. These are enemy boxes wholly on screen, matched / not-found, with boxes
    partly on screen in brackets:
    - `hold-right`: 31 / 0 (3).
    - `reverse`: 25 / 0 (7).
    - `move-fire-right`: 16 / 9 (3).
  - The counts were identical on all three builds. So on these probes `visible` about the enemy
    reaches neither defect.
  - The 9 `not-found` on `move-fire-right` are on the clean game and were not diagnosed. Under the
    keep rule they drop a check; they cannot make a false catch.
- Full suite on the branch (main f161c81 plus the change): see the pull request.

Nothing was dispatched and nothing was spent.

## Not done
- **`enemy-walks-backwards` is not reached.** Every template is kept mirrored, so the sensor cannot
  tell which way a sprite faces. Reaching it needs a facing observation (the matched template's
  mirroring against the engine's direction of motion) and a predicate to judge it. That would be a
  contract change to pixel checks.
- The bullet: it needs a smaller sample grid or its own settings before its crops give templates.
- The 9 clean `not-found` enemy boxes on `move-fire-right` are not explained.
- A whole-window enemy check is `needs-review` whenever an enemy enters at the screen's edge. Partial
  boxes are not matched.
- No jit.yml run has used the sensor. The `sensor-bank` job replays the same routes as before and now
  also calibrates the enemy. Here its bank is 7.3 MB larger (34.8 MB) and the calibration step alone
  took 3 min 40 s; the whole job was not timed end to end with this change, here or in CI.

## Files
- `agents/template_observations.py`
- `agents/template_foreground.py`
- `contracts/template-bank.schema.json`
- `contracts/observations.schema.json`
- `contracts/examples/template-bank-foreground-named.json`
- `expectrail/jit/template_observer.py`
- `expectrail/jit/pixel.py`
- `docs/jit.md`
- `docs/template-sensor.md`
- `tests/test_jit_sensor_named.py`
- `tests/test_jit_pixel.py`
- `tests/test_jit_sensor_workflow.py`
- `tests/test_jit_propose_observer.py`
- `docs/new-work/2026-11-16-sensor-enemy.md`
