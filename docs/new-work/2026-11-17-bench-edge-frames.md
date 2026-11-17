# The public bench's screen-only enemy and bullet records say which frames to avoid (#286)

## What changed
#582 added `edges` to the evidence record (the clean game's frames where an enemy or a bullet is only
partly on screen, which the no-model sensor does not judge) but left the bench's committed records without
them, so a pixel-setting propose step given those records had no frames to avoid.

- `bench/jit/public/evidence-enemy-walks-backwards.json` and `evidence-bullet-behind-scenery.json`: made
  again on all 25 library probes. Every field of every row is what the November 11 records held; each row
  now also has `edges`.
- `expectrail/repro/evidence.py` `render`: a record with `edges` gets one line under its table naming, per
  probe, the frames where each kind is partly on screen ("cannot say" where the record cannot). A record
  without `edges` renders exactly as before.
- `bench/jit/public/README.md`: both sections rendered again from the records, and a paragraph on what was
  remade. `docs/jit.md`: what the remade records show.
- `tests/test_repro_evidence_edges.py`: the rendering (4 tests) and the two bench records (5 tests: every
  row carries both kinds, the two records agree on them, the November 16 example's three probes read the
  same, the four probes where the enemy is never wholly on screen, and the pixel setting gets them while
  the evidence setting does not).

## What was run
- `python3 -m expectrail.repro evidence --defect enemy-walks-backwards --out runs/ev-ewb --jobs 2` on
  Godot 4.7.2 here, no model: 13 min 15 s, 25 probes, screen-only 25, errors 0.
- `python3 -m expectrail.repro evidence --defect bullet-behind-scenery --out runs/ev-bbs --jobs 2`: 13 min
  1 s, 25 probes, screen-only 6, nothing differs 19, errors 0.
- Each new record compared with the committed one by script: no top-level field differs, and every row is
  the same once `edges` is removed. The two records' `edges` are the same (they come from the clean game).
- What `edges` shows for the enemy: partly on screen on every frame of `jump-w0-x1`, `jump-w0-x2`,
  `shoot-right-every48` and `shoot-right-every12`; on 15 probes no frame after 27 has it partly on screen.
- `python3 -m unittest tests.test_repro_evidence_edges tests.test_repro_evidence tests.test_jit_offer_evidence`:
  104 tests, OK.
- The full suite on the branch: see the pull request.

## Not done
- The `coin-stays` and `no-shooting-in-air` records were not remade and have no `edges`. Neither defect is
  screen-only, and neither is about how an enemy or a bullet is drawn.
- No model has proposed a check with these frames in front of it: that is a live propose step (money).
- The records were not made in CI.

## Files
- `bench/jit/public/evidence-enemy-walks-backwards.json`
- `bench/jit/public/evidence-bullet-behind-scenery.json`
- `bench/jit/public/README.md`
- `expectrail/repro/evidence.py`
- `docs/jit.md`
- `tests/test_repro_evidence_edges.py`
- `docs/new-work/2026-11-17-bench-edge-frames.md`
