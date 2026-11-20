# Metamorphic checks: mirror the inputs, judged over the clear window (#675, piece 3, slice 1)

## What changed

- New trace-spec operation `metamorphic` (`transform: mirror_x`) in `contracts/trace-spec.v1.schema.json`,
  with an example `contracts/examples/trace-spec-metamorphic.v1.json`, interpreted by
  `expectrail/trace/evaluator.py` (version 1.2.0). The twin probe is the left probe with each paired
  action swapped; the evaluator checks the twin's inputs are exactly that mirror ("cannot tell"
  otherwise). Sideways travel (`player_dx_px`) must negate; `max_rise_px`, `airborne_ticks` and
  `air_jumps` must stay equal. The schema allows only those signal and relation pairings.
- The **clear window**: the relation is judged from the first mirrored input to the tick before either
  twin touches something the mirror did not also move, read from motion no input explains (a wall or
  another body, a ceiling, moving ground, landing at another height, leaving the ground with no input,
  an enemy within 48 px). The bounds are fixed in `MIRROR`, never in a spec. A window with under 8 px of
  sideways motion, or an equal signal that is 0 on both twins, is not exercised, never a pass.
- `expectrail/jit/metamorphic.py` (new) derives the mirrored probe and the four checks from any probe, in
  the generator's entry shape. It is not wired into the generator: that is slice 2.
- `tools/metamorphic_public.py` (new) measures them on the bundled game, the player's do-nothing control
  and the 24 public defects; `--resume` judges saved replays again without re-running them.
- `docs/measurements/675-metamorphic-mirror.md` (new), a section in `docs/jit.md` and one in
  `docs/discovery.md`.

## What was run

- `python3 tools/metamorphic_public.py --work /tmp/.../full --out ...` on Godot 4.7.2, no model: 840
  replays (28 routes; clean and control 3 times, each defect once). Then, after the sideways bound
  change described in the measurement, `--resume` on the same replays. Result: 56 checks, 28 pass the
  clean game 3 of 3, 0 pass the do-nothing control, 14 catch `slow-left`, 0 fail on the other 23 defects.
- `python3 -m unittest tests.test_trace_metamorphic`: 30 tests, OK.
- Full suite, see the pull request for the final run.

## Not done

- Slice 2: the generator offers metamorphic checks (`run.py`, `jit-run.v1`) as advisory rows, under the
  same validity rule including the do-nothing control.
- Slice 3: one outside game with keyboard left/right.
- A mirror for enemies (their own direction) or for facing is not attempted.
- Nothing here changes what may count or clear a change.

## Files

- `contracts/trace-spec.v1.schema.json`, `contracts/examples/trace-spec-metamorphic.v1.json`
- `expectrail/trace/evaluator.py`, `expectrail/jit/metamorphic.py`
- `tools/metamorphic_public.py`
- `tests/test_trace_metamorphic.py`
- `docs/measurements/675-metamorphic-mirror.md`, `docs/jit.md`, `docs/discovery.md`
- `docs/new-work/2026-11-20-metamorphic-mirror.md`
