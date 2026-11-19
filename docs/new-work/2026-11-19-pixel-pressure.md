# Correct-fix pressure replays counting pixel checks judged by the no-model sensor (#271)

## What changed
- `expectrail/jit/pressure.py`: `pressure correct --sensor-bank BANK` replays each counting pixel check
  judged by `visual-sensor` on every correct fix: three replays with frames, the sensor asked about the
  planned frames inside the checks' windows, `pixel.judge` on each run. A gap, `needs-review` or an
  observer failure is `insufficient_observation` (blocked, never complete). The bank's setting must equal
  the one in the signed source run (`pixel-setting-mismatch` otherwise). Still stopped:
  a counting pixel check for SAM, a correct dispatch with no bank, and the adversary.
- The frame plan is pinned too (after the merge guard's review): `jit run` writes `framesPlanned` on each
  pixel row (`pixel.record_row`, `run._pixel_stage`; contract `jit-run.v1`, optional field), and pressure
  stops before any replay unless its observer plans exactly those frames for the check
  (`pixel-plan-mismatch`), or when a row records no plan (`pixel-plan-unrecorded`).
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
  OK (new file: 26 tests; one more in `tests/test_jit_template_observer.py` for the writer). The guard's
  probe (a sensor planning 2 frames) is now a test: it stops with `pixel-plan-mismatch` and replays nothing.
- Real engine, Godot 4.7.2, no model: `sensor-bank` (7 min 18 s, digest `b033bf03...`, identical to the
  stand-in's judging bank), then correct pressure on the enemy stand-in made counting with a throwaway
  key and given the plan this observer makes (15, 5 and 14 frames): exact undo pass 9 of 9 runs
  (`complete`); no-fix control fail 9 of 9 (`failed`). Run before and again after the plan check, same
  outcomes. Sandbox `auto` (no Bubblewrap here).
- Full suite: see the pull request.

## Not done
- Recorded SAM answers are not replayed; a counting SAM pixel check still stops the dispatch.
- The workflow proposal `docs/proposals/271-pressure.yml.txt` has no bank job; unchanged.
- No live campaign; nothing dispatched.

## Files
- `expectrail/jit/pressure.py`, `expectrail/jit/pixel.py`, `expectrail/jit/run.py`
- `contracts/jit-run.v1.schema.json`, `contracts/examples/jit-run-pixel.json`, `contracts/jit-pressure.v1.schema.json`, `contracts/examples/jit-pressure-pixel.json`
- `tests/test_jit_pixel_pressure.py`, `tests/test_jit_template_observer.py`
- `docs/jit.md`, `docs/measurements/271-pixel-pressure.md`, `docs/measurements/271-pixel-pressure.json`
- `docs/new-work/2026-11-19-pixel-pressure.md`
