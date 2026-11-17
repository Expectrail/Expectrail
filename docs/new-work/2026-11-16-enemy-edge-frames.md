# The proposer is told which frames have an enemy only partly on screen (#286)

## What changed
The no-model sensor does not judge an object whose box reaches past the frame's edge, so a pixel check
about the enemy whose window holds such a frame is undecided (`needs-review`). On every bench probe the
enemy enters at an edge, so a whole-window `faces-motion` check could never be decided.

- `expectrail/repro/evidence.py`: each evidence row gets `edges`: per object kind the engine logs boxes for
  (enemy, bullet), the captured frames of the clean game where one is partly on screen, as runs, from both
  clean replays (null where the record cannot say or the replays disagree). The reader checks the runs.
  `for_proposer` carries them as `partlyOnScreen`.
- `contracts/repro-evidence.v1.schema.json`: the optional `edges` field. Records without it still read.
  New example from a real run: `contracts/examples/repro-evidence-edges.json`.
- `expectrail/jit/offer.py`, `expectrail/jit/intent.py`: under the pixel setting only, a shown probe's
  `differs` carries `partlyOnScreen`, and the pixel text says to avoid those frames. The pixel text now
  also gives `faces-motion`'s shape, which the prompt offered but never described.
- `expectrail/jit/pixel.py`: a gap for a box partly off screen says so.

## What was run
- `python3 -m expectrail.repro evidence --defect enemy-walks-backwards --probe hold-right --probe reverse
  --probe move-fire-right --jobs 2` on Godot 4.7.2 here: 3 minutes, all three probes compared. Enemy partly
  on screen: frames 0-15 and 17-27 on `hold-right` and `move-fire-right`, plus 87-96, 98-112 and 114-124 on
  `reverse`. The windows chosen by hand on #571 (from frames 30, 130 and 30) are past all of them.
- `python3 -m unittest tests.test_repro_evidence_edges`: 15 tests, OK.
- The full suite on the branch: see the pull request.

## Not done
- No model has proposed a check with these frames in front of it. That needs a live propose step (money).
- The SAM observer is not changed; whether SAM judges a partly visible enemy is not measured here.
- The committed bench evidence records under `bench/jit/public/` were not remade, so they have no `edges`.

## Files
- `expectrail/repro/evidence.py`
- `contracts/repro-evidence.v1.schema.json`
- `contracts/examples/repro-evidence-edges.json`
- `expectrail/jit/offer.py`
- `expectrail/jit/intent.py`
- `expectrail/jit/pixel.py`
- `docs/jit.md`
- `tests/test_repro_evidence_edges.py`
- `docs/new-work/2026-11-16-enemy-edge-frames.md`
