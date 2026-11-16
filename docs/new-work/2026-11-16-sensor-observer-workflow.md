# jit.yml can judge pixel checks with the no-model template sensor: an `observer` input and a bank job (#286)

## What changed
- `jit.yml` has an `observer` input: `sam-3.1-anchor` (the default; every job and command line as before)
  or `visual-sensor`. The plan refuses `visual-sensor` without the pixel setting, and any other value.
- With `visual-sensor`:
  - propose and revise get `--observer visual-sensor`, so the proposer is offered only what the sensor can
    tell (whether and where the player is drawn);
  - a new `sensor-bank` job calibrates the sensor's bank once a run on the clean game alone: no secret, no
    environment, no patch, no artifact of the change;
  - replay-final judges the pixel checks with that bank (`--observer visual-sensor --sensor-bank BANK
    --sam-every N`), and its record is the result (`jit-<case>`, not `-captured`);
  - pixel-ask and pixel-judge do not run. If the bank job fails, replay-final does not run.
  - the bank job and replay-final install Pillow 12.3.0 and NumPy 2.5.3, which the sensor needs and
    `requirements-dev.txt` does not have.
- `python -m expectrail.jit.cli sensor-bank --out BANK --work DIR` (`template_observer.calibrate_bank`):
  replays the four dedicated clean routes of the published sensor measurement and freezes a
  `template-foreground/v3` bank from the player's clean art and pose catalogue. It refuses to overwrite a
  bank, to reuse a work folder, or to write inside the game.
- One existing assertion changed: replay-final's artifact name now carries the observer condition
  (`tests/test_jit_pixel_workflow.py`).

## What was run
- `python3 -m unittest tests.test_jit_sensor_workflow`: 31 tests, OK (structure of every job, the plan's
  refusals, each step's call with a stand-in for `python`, the real parser on propose's and revise's
  arguments, `calibrate_bank` with a stand-in game).
- On the real engine here (Godot 4.7.2 from `harness/get_godot.sh`, Xvfb, no model, not in CI):
  `python3 -m expectrail.jit.cli sensor-bank --out .../bank.json --work .../work` took 4 min 57 s and
  printed 408 templates, algorithm `expectrail.template-foreground/v3`, bank digest
  `f9895bbe39bd208bbc3a4fa2fd65e3abeb5d788fe62bed8494f494703edcfe5b`, 27.5 MB. Two earlier calibrations
  through a scratch script with the same routes gave byte-identical banks (raw SHA-256 `84c1bf00...`).
- `TemplateSensorObserver` with that bank on clean replays of `harness/routes/coins.json` and
  `traversal.json`: every planned frame `matched` (13 and 19 frames at every 10th frame, 25 and 27 at
  every frame), 0 `not-found`, 0 `displaced`, 0 images. Two public routes, not the bench's probes.
- Full suite on the branch (main f7e1110 plus the change): see the pull request.
- Nothing was dispatched and nothing was spent.

## Not done
- No dispatch of `jit.yml` with `observer: visual-sensor` (it spends model money on propose and revise).
- The sensor sees only the player. The bench's screen-only defects (the coin counter, the enemy, the bullet)
  are not things it can judge; that needs templates and prediction maps for other sprites.
- No false-alarm rate measured on the bench's probes with this bank.

## Files
- `.github/workflows/jit.yml`
- `expectrail/jit/template_observer.py`, `expectrail/jit/cli.py`
- `tests/test_jit_sensor_workflow.py`, `tests/test_jit_pixel_workflow.py`
- `docs/jit.md`, `docs/new-work/2026-11-16-sensor-observer-workflow.md`
