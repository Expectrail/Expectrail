# Correct-fix pressure replays counting pixel checks judged by the no-model sensor (#271)

## What changed
- `expectrail/jit/pressure.py`: `pressure correct --sensor-bank BANK` replays each counting pixel check
  judged by `visual-sensor` on every correct fix: three replays with frames, the sensor asked about the
  planned frames inside the checks' windows, `pixel.judge` on each run. A gap, `needs-review` or an
  observer failure is `insufficient_observation` (blocked, never complete). The bank's setting must equal
  the one in the signed source run (`pixel-setting-mismatch` otherwise). Still stopped:
  a counting pixel check for SAM, a correct dispatch with no bank, and the adversary.
- Trace replays now replay only the probes trace checks name (before, every route in the bundle, which
  was the same set).
- Contract `jit-pressure.v1`: optional row `kind: "pixel"` and optional `pixelObserver` (name, setting,
  frame plan). Writer `execute`, reader `check` (pixel rows need `pixelObserver`; the adversary never has
  one), new example `contracts/examples/jit-pressure-pixel.json`. The old example still reads.
- `docs/jit.md`: new section "Pixel checks under correct-fix pressure"; the test plan's adversary line no
  longer says "Not built yet" (it was built on November 16 as a prepared dispatch).
- `docs/measurements/271-pixel-pressure.md` and `.json`: a real-engine rehearsal.

## What was run
- `python3 -m unittest tests.test_jit_pixel_pressure tests.test_jit_pixel_envelope tests.test_jit_rules`:
  OK (new file: 22 tests).
- Real engine, Godot 4.7.2, no model: `sensor-bank` (7 min 18 s, digest `b033bf03...`, identical to the
  stand-in's judging bank), then correct pressure on the enemy stand-in made counting with a throwaway
  key: exact undo pass 9 of 9 runs (`complete`); no-fix control fail 9 of 9 (`failed`). Sandbox `auto`
  (no Bubblewrap here).
- Full suite: see the pull request.

## Not done
- Recorded SAM answers are not replayed; a counting SAM pixel check still stops the dispatch.
- The workflow proposal `docs/proposals/271-pressure.yml.txt` has no bank job; unchanged.
- No live campaign; nothing dispatched.

## Files
- `expectrail/jit/pressure.py`
- `contracts/jit-pressure.v1.schema.json`, `contracts/examples/jit-pressure-pixel.json`
- `tests/test_jit_pixel_pressure.py`
- `docs/jit.md`, `docs/measurements/271-pixel-pressure.md`, `docs/measurements/271-pixel-pressure.json`
- `docs/new-work/2026-11-19-pixel-pressure.md`
