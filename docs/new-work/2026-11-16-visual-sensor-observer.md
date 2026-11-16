# The no-model template sensor judges pixel checks as the `visual-sensor` observer (#286)

## What changed
Issue #286 asks for pixel checks judged by trusted observers, "the no-model visual sensor (#262) by
default, SAM 3.1 when configured". Until now `visual-sensor` was declared and refused ("not built yet"),
so the only observer was SAM, and every pixel run needs a live SAM call that costs money.

- `expectrail/jit/template_observer.py`: `TemplateSensorObserver`, the `visual-sensor` observer. It
  wraps #262's sensor (`agents/template_observations.py`, unchanged) over a template bank frozen
  beforehand from a clean replay, and looks for the player near the engine's body box on the planned
  frames. It sends nothing and returns `images: 0`. Its setting is the sensor's algorithm and the bank's
  digest. A sensor `matched` row is seen; `displaced` is looked for and not found there; `not-found` is
  `absent` (an observation, not a gap); `unavailable` and `out-of-frame` are not asked (a gap, so
  `needs-review`). Named objects (enemy, bullet) and `reaches` are refused: the bank holds the player only.
- `expectrail/jit/sam_observer.py`: the replay checks and the frame plan are moved out of the SAM
  observer into `checked_replay` and `plan_frames`, unchanged, so both observers check a replay folder the
  same way and plan the same frames.
- `expectrail/jit/pixel.py`: `OBSERVERS["visual-sensor"]` now declares what the sensor can judge
  (`visible`, `inside-region`, `never-crosses`; the player; not the ground or text). `observations` reads
  an `absent` row as an observation with no detection. `PROPOSED` and `proposed()`: the proposer is
  offered only SAM, and `parse_answer` reads a model's checks only against SAM, because the propose step
  is not told which observer will judge the run, and a check naming another observer is not run.
- `expectrail/jit/intent.py`: a saved proposal's pixel checks are re-checked against `pixel.proposed()`,
  so a proposal edited from SAM to the sensor is still refused.
- `expectrail/jit/run.py`: the pixel stage reserves what the observer says a replay can take at most
  (`most_images`) when it says so, so the sensor reserves $0; an observer without it is reserved as before.
- `docs/jit.md`: a section on the sensor as an observer.

The pixel setting's prompt changes in one place: `notJudgeable` no longer carries the line
"visual-sensor: the no-model visual sensor (#262) is not built yet". No other setting's prompt changes.

Test changes to existing files:
- `tests/test_jit_pixel.py`: the refusal case "cannot judge anything yet" named `visual-sensor`, which is
  now available. It moved to its own test with a table where the sensor is unavailable, so the branch is
  still tested; a new test holds what the sensor can and cannot judge and that a proposal may not name it.
- `tests/test_jit_pixel_offer.py`: `assertIn("not built yet", notJudgeable["coin"])` becomes
  `assertNotIn("visual-sensor", ...)`: the sensor is built and not offered to the proposer.

## What was run
- `python3 -m unittest tests.test_jit_template_observer`: 19 tests, OK. Synthetic frames and a bank
  calibrated from a synthetic clean replay; end to end through `run.generate` on the simulated game, a
  check that the player is drawn is kept (pass 3 of 3 on the clean game, fail 3 of 3 where the sprite is
  not drawn), catches a wrong fix and not a good one, with $0 reserved and 0 SAM images.
- The pixel and SAM test modules (`tests.test_jit_pixel*`, `tests.test_jit_sam_observer`,
  `tests.test_repro_pixel_reach`, `tests.test_repro_score_pixel`): OK.
- The full suite on the branch merged with main 8d8cb4d (`python3 -m unittest discover -s tests -t .`, after
  the pinned fetch): 4,169 tests, OK, 43 skipped.
- No engine, no model, no SAM call, no dispatch. Nothing was spent.

## Not done
- The proposer is not offered the sensor. Next: the propose step takes the observer that will judge the
  run, the proposal records it, the menu offers that observer, and `run` refuses a proposal made for
  another; then `--observer visual-sensor --sensor-bank FILE` on the command line and in jit.yml.
- No bank has been calibrated for a bench probe, and the sensor has not judged a bench defect's frames.
- Named objects (enemy, bullet) need their own templates and prediction maps.

## Files
- `expectrail/jit/template_observer.py` (new)
- `expectrail/jit/sam_observer.py`, `expectrail/jit/pixel.py`, `expectrail/jit/intent.py`, `expectrail/jit/run.py`
- `tests/test_jit_template_observer.py` (new), `tests/test_jit_pixel.py`, `tests/test_jit_pixel_offer.py`
- `docs/jit.md`, `docs/new-work/2026-11-16-visual-sensor-observer.md`
