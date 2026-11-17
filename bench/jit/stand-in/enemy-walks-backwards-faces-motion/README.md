# A hand-written `faces-motion` stand-in for `enemy-walks-backwards` (#286)

**No model wrote these checks.** They are not a reproduction and the reproduction score gives a record made
from them no result (`expectrail/repro/score.py`, `STAND_INS`).

- `jit-proposal.json`: three `faces-motion` pixel checks about the enemy, judged by the no-model sensor,
  written by `python3 -m tools.faces_motion_stand_in --out <dir>`. They are the windows measured by hand on
  November 16 (`docs/jit.md`, "Which way the enemy faces"): `hold-right` from frame 30, `reverse` from 130,
  `move-fire-right` from 30. Each starts after the last frame the bench's evidence lists the enemy as partly
  on screen on that probe. The proposal is made under `signals-reach-evidence-pixel` with the candidate
  withheld, so it is bound to the bench's report and to no patch.
- `jit-run.json`: `jit run --proposal` on that file, on the real engine, on November 17, 2026.

## The run

Godot 4.7.2-stable (`harness/get_godot.sh`), Xvfb, a cloud container with 2 CPUs, no model key in the
environment. The bank was calibrated first with `python3 -m expectrail.jit.cli sensor-bank` (5 minutes; 408
player and 148 enemy templates, enemy `met`, digest `b033bf03...`). The bank is not committed (34.8 MB).

```
python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/enemy-walks-backwards/report.txt \
  --base bench/jit/public/enemy-walks-backwards/defect.patch \
  --candidate bench/jit/public/no-fix.patch \
  --proposal bench/jit/stand-in/enemy-walks-backwards-faces-motion/jit-proposal.json \
  --out OUT --budget-usd 1 --model off --run-id local-faces-motion-stand-in \
  --offer signals-reach-evidence-pixel --withhold-candidate \
  --observer visual-sensor --sensor-bank BANK --sam-every 10
```

It took 13 minutes, 27 replays with frames. Every check was kept by the keep rule from its own runs:

| Check | Clean game | Bug build | Bug build plus the no-fix candidate |
| --- | --- | --- | --- |
| `hold-right`, from frame 30 | pass 3 of 3 | fail 3 of 3 | fail 3 of 3 |
| `reverse`, from frame 130 | pass 3 of 3 | fail 3 of 3 | fail 3 of 3 |
| `move-fire-right`, from frame 30 | pass 3 of 3 | fail 3 of 3 | fail 3 of 3 |

The record's spend, $0.2159, is its own accounting at assumed prices: $0.1247 for the intent call, which
the run reserves even when it replays a saved proposal, and $0.0912 of assumed runner time. No model was
called and nothing was paid. SAM was asked about 0 images.

## What this shows and what it does not

It shows that the keep rule, run by `jit run` itself on the real engine, keeps a `faces-motion` check on
this defect: three clean runs and three bug runs, where the November 16 measurement had two clean runs and a
hand script. It does not show that a model, given the same evidence, proposes such a check. That needs a
live propose step under `signals-reach-evidence-pixel` with `observer: visual-sensor`.
