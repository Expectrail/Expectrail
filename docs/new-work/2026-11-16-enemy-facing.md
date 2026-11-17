# Pixel checks can say which way the enemy is drawn facing: `faces-motion` (#286)

## What changed
The no-model sensor keeps every template mirrored, so `visible` matches an enemy drawn facing backwards,
and no pixel check could reach `enemy-walks-backwards`. A new predicate, `faces-motion`, says the object
is drawn facing the way the engine's record moves it. The sensor now tells which way the enemy faces,
and the bank records how well it does so.

- `agents/template_observations.py`: `object_motion(trace, frames, role)` reads which way the engine moves
  each object, from its own logged world box on the tick before, the frame's tick and the tick after.
  The answer is `right` or `left` when both steps go that way. Otherwise it is `still`, `turning`, or None
  when the record cannot say.
- `agents/template_foreground.py`:
  - `calibrate_routes` labels each clean enemy capture with the way the engine moved the cropped enemy on
    that tick (`heading`), and its mirrored copy the other way. A pose that looks the same mirrored
    (`symmetric`, the rule that keeps two templates apart) gets no label.
  - `facing` decides which way a drawn object faces: the heading whose labelled templates match better,
    by at least `FACING_MARGIN` (0.02). Otherwise it gives None, which means the sensor cannot tell.
  - `_validate_facing` runs on every validation frame where the enemy moves one way. It decides the
    facing as drawn, then again with the enemy mirrored in place (`mirrored_about`). The record goes under
    `calibration.objects.enemy.facing`, and `met` follows the player's rule on both.
  - The reader (`check_bank`, `_check_facing`) recomputes that status. It refuses:
    - labels its record does not count;
    - a label on a pose that looks the same mirrored, or on anything but a clean capture;
    - labels with no facing record;
    - a facing record for an object other than the enemy.
- `expectrail/jit/template_observer.py`:
  - When the bank's enemy facing is `met`, every enemy box row carries `motion`.
  - A box `matched` while the enemy moves one way also carries `facing` and both scores.
  - The run lists the roles whose facing it tells (`facing`).
- `expectrail/jit/pixel.py`:
  - `faces-motion` is in the closed language, for `visual-sensor` and the enemy only (`OBSERVERS[...]["facing"]`).
    SAM, and any other object, are refused at proposal time with the reason, and the sensor's menu says so.
  - `_facing_observations` judges it over the frames where the enemy moves one way and is matched. Such a
    frame holds the enemy when it is drawn facing its motion, and the reference evaluator's `visible`
    decides.
  - These are gaps: a moving, matched enemy whose facing was not told or could not be told, and a run that
    does not list the enemy in `facing`.
  - `observe` refuses an answer that claims facing for an object it was not asked about.
- Contracts:
  - `contracts/pixel-check.v1.schema.json` gains `faces-motion`, with a new example
    `contracts/examples/pixel-check-facing.json`.
  - `contracts/template-bank.schema.json` gains the optional template `heading` and
    `calibration.objects.enemy.facing`.
  - `contracts/observations.schema.json` gains the same calibration field.
  - There is a new synthetic bank example, `contracts/examples/template-bank-foreground-facing.json`.
  - The writers and the readers are in this pull request.
- Docs: `docs/jit.md` ("Which way the enemy faces") and `docs/template-sensor.md`.

## What was run
- `python3 -m unittest tests.test_jit_sensor_facing`: 21 new tests, OK. They cover:
  - motion, and the record that cannot say;
  - the labels and the facing validation;
  - the reader's recomputation and five forgeries;
  - a symmetric pose;
  - the observer's rows;
  - a backwards enemy failing `faces-motion` while still passing `visible`;
  - one backwards frame, two enemies walking opposite ways, and a standing enemy not judged;
  - the keep rule, where `visible` gives `does-not-fail-on-bug`;
  - an unmet bank, an untold facing and a forged answer, each failing closed;
  - the language and both examples.
- `tests/test_jit_propose_observer.py`: the sensor's menu now lists `faces-motion` and says it is about the
  enemy only. That assertion was changed on purpose (see the pull request's guard line).
- On the real engine here (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb; no model, not in CI):
  - `python3 -m expectrail.jit.cli sensor-bank` took 375 s. It gave the same 408 player and 148 enemy
    templates as before (34.8 MB). All 148 enemy captures were cut while the enemy walked right, so 74 are
    labelled `right` and their 74 mirrored copies `left`.
  - Enemy facing on the validation replay: 251 moving frames. 251 were decided right as drawn, 251 were
    decided the other way when mirrored, and 0 were wrong (`met`).
  - `hold-right`, `reverse` and `move-fire-right`, every 10th frame, the clean game twice and each defect
    build once. On every clean replay, every enemy box matched while moving was decided facing its motion
    (29, 23 and 15). On `enemy-walks-backwards`, every one was decided facing against it (29, 23 and 15).
    No box was undecided.
  - A `faces-motion` check over the whole window was `needs-review` on all of them: an enemy enters at the
    screen's edge, and partial boxes are gaps. Windowed past those frames (from frame 30, 130 and 30), it
    passed both clean replays, failed the backwards build and passed `enemy-slides-when-shot` on all three
    probes. `visible` over the same windows gave the same result on the clean game and the backwards build.
  - The nine clean `not-found` enemy boxes on `move-fire-right` (left undiagnosed by the last change) have
    motion `still`: enemies that were shot and stopped.
- Full suite on the branch (main d36c806 plus the change): see the pull request.

Nothing was dispatched and nothing was spent.

## Not done
- The checks measured above were written by hand. No model has proposed a `faces-motion` check, and no
  jit.yml run has judged one. There were two clean replays, not the keep rule's three.
- In these probes the enemies only ever walk right. The `left` templates are mirrored copies, validated
  only on the validation replay's mirrored frames, not on an enemy drawn walking left by the game.
- A whole-window enemy check is still `needs-review` whenever an enemy enters at the screen's edge. The
  proposer is not told to pick a window that avoids those frames.
- The bullet and the player have no facing.

## Files
- `agents/template_observations.py`
- `agents/template_foreground.py`
- `expectrail/jit/template_observer.py`
- `expectrail/jit/pixel.py`
- `contracts/pixel-check.v1.schema.json`
- `contracts/template-bank.schema.json`
- `contracts/observations.schema.json`
- `contracts/examples/pixel-check-facing.json`
- `contracts/examples/template-bank-foreground-facing.json`
- `docs/jit.md`
- `docs/template-sensor.md`
- `tests/test_jit_sensor_facing.py`
- `tests/test_jit_propose_observer.py`
- `docs/new-work/2026-11-16-enemy-facing.md`
