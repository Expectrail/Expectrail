# The keep rule keeps `faces-motion` on `enemy-walks-backwards`, through `jit run` itself (#286)

## What changed
- `tools/faces_motion_stand_in.py` writes a saved proposal of the three windowed `faces-motion` checks measured
  by hand on November 16 (`hold-right` from frame 30, `reverse` from 130, `move-fire-right` from 30). It is
  written through `intent.propose_to_file` and the pixel parser a model's answer goes through, under
  `signals-reach-evidence-pixel`, for `visual-sensor`, with the candidate withheld. It refuses a window that
  starts on or before a frame the bench's evidence lists the enemy partly on screen, and evidence that cannot
  say. `model` is `hand-written-stand-in`, and a diagnostic says no model was called.
- `bench/jit/stand-in/enemy-walks-backwards-faces-motion/`: the proposal, the record of its run, and a
  README with the command and the result.
- `expectrail/repro/score.py`: a record whose `inputs.model` is one of the repository's stand-ins (`STAND_INS`:
  `rehearsal-fixture`, `hand-written-stand-in`) is no result, with the reason. Before this, the scorer counted
  the stand-in's record as a reproduction of `enemy-walks-backwards` (measured: 1 reproduced, 1 screen-only
  reproduced). No schema change: `why` already carries the reason, and the reader's rule for `no-result` holds.
- `docs/jit.md`: a paragraph under "Which way the enemy faces".

## What was run
- On the real engine here (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb, no model key in the
  environment; not in CI):
  - `python3 -m expectrail.jit.cli sensor-bank`: 5 minutes, 408 player and 148 enemy templates, enemy `met`,
    bank digest `b033bf03e7c5...`.
  - `python3 -m expectrail.jit.cli run --proposal <the stand-in> --offer signals-reach-evidence-pixel
    --withhold-candidate --observer visual-sensor --sensor-bank BANK --sam-every 10` against
    `enemy-walks-backwards` and `no-fix.patch`: 13 minutes, 27 replays, status `complete`. All three checks
    `kept`: clean pass 3 of 3, bug fail 3 of 3, bug plus no-fix candidate fail 3 of 3. The record says $0.2159
    at assumed prices (the reserved intent call and runner time); no model was called and nothing was paid.
  - `python3 -m expectrail.repro score` on that record, before the scorer change: `enemy-walks-backwards`
    reproduced. After it: no result, "the checks were written by hand".
- `python3 -m unittest tests.test_faces_motion_stand_in`: 14 new tests, OK.
- Full suite on the branch (main bf31c92 plus the change): see the pull request.

## Not done
- A model proposing a `faces-motion` check: needs a live propose step under the pixel setting with
  `observer: visual-sensor` (Sean).
- The bank is not committed (34.8 MB); its digest is in the record.

## Files
- `tools/faces_motion_stand_in.py` (and its line in `.gitignore`, which ignores `tools/` but for named files)
- `bench/jit/stand-in/enemy-walks-backwards-faces-motion/jit-proposal.json`, `jit-run.json`, `README.md`
- `expectrail/repro/score.py`
- `tests/test_faces_motion_stand_in.py`
- `docs/jit.md`, `bench/jit/README.md`
- `docs/new-work/2026-11-17-faces-motion-keep-rule.md`
