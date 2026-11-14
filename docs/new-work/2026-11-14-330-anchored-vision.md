# Anchored vision for outside games (#330)

## What changed

- Cause of 0 of 120: the outside judge used the bundled game's spec ("blue robot") on a grey-square
  player. The question was wrong, not the model.
- `expectrail/anchored.py`: `AnchoredObserver` asks what is drawn inside the engine's body box;
  `calibrate` measures found, size and stable rates on the clean run against `RULES`, fixed today
  before any live outside answer; `check_calibration` refuses a calibration whose verdict does not
  follow from its own frames, or that uses other rules.
- Contract `expectrail.vision-calibration/v1`: schema, example, writer (`calibrate`) and reader
  (`check_calibration`).
- `tools/outside_vision.py judge` calibrates first, then judges; it records the live answers
  (`vision-recording.json`), and `--recording` replays them with no key and no spend. The workflow
  keeps the calibration and the recording, and shows the calibration in the summary.

## What was run

- `python3 -m unittest discover -s tests -t .`: 3,311 tests; the two failures it found (the wheel
  list and this entry's sections) are fixed, and those modules pass.
- `tests/test_anchored_observer.py` (13 tests) with stand-in models only: one that sees the player,
  one that echoes the box it was given (refused by the stable rule), one that answers nothing, one
  that stops (no calibration). No live model was asked.

## Not done

- The live run on kinematic-character (Sean dispatches, after merge).
- Replaying the recording in the CI outside trial: that needs byte-identical frames between capture
  runs, which the first recording will show.

## Files

- `expectrail/anchored.py`
- `contracts/vision-calibration.v1.schema.json`
- `contracts/examples/vision-calibration.v1.json`
- `tools/outside_vision.py`
- `.github/workflows/outside-vision.yml`
- `tests/test_anchored_observer.py`
- `tests/test_package.py`
- `docs/outside-projects.md`
- `docs/new-work/2026-11-14-330-anchored-vision.md`
