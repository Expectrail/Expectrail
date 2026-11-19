# A hand-written `visible` bullet stand-in for `bullet-behind-scenery`, for the no-model sensor (#286)

**No model wrote these checks.** They are not a reproduction, and the reproduction score gives a record made
from them no result (`expectrail/repro/score.py`, `STAND_INS`).

`bullet-behind-scenery` changes the bullet's `z_index` from 5 to -5, so the bullets are drawn behind the
platforms and rocks. Nothing in the engine's record changes. Since November 19 the no-model sensor
(`visual-sensor`) can be asked about the bullet: its bank witnesses it by its rings
(`agents/template_radial.py`), with no model and no charge.

- `jit-proposal.json`: two `visible` checks about the bullet, `minFraction` 1.0, written by
  `python3 -m tools.bullet_visible_stand_in --out <dir> --observer visual-sensor`. Made under
  `signals-reach-evidence-pixel` with the candidate withheld, so it is bound to the bench's report and to no
  patch.

  | Probe | Window | Planned frames in it |
  | --- | --- | --- |
  | `shoot-left-every12` | frames 50 to 50 | 1 |
  | `move-fire-right` | frames 10 to 30 | 3 |

  The windows are the SAM stand-in's (`../bullet-behind-scenery-visible/`), cut short: the sensor does not
  judge a bullet in its fade (the last 0.3 s of its life) or a bullet whose searched path another logged box
  touches (`crowded` in `agents/template_radial.py`), a gap either way. Each window ends at the last planned
  frame before the first planned frame with such a bullet on screen on the clean game's replay, read from the
  trace alone: frame 60 of `shoot-left-every12` and frame 40 of `move-fire-right`. `move-fire-left` has one at
  frame 90, where its SAM window starts, so it is left out.
- `jit-run.json`: the run's record (below).

## The run

Godot 4.7.2-stable (`harness/get_godot.sh`), Xvfb, a cloud container, no model key and no SAM key in the
environment. November 19, 2026, on main 8c2f9a2 plus the change, remade after the crowded rule.

```
python3 -m expectrail.jit.cli sensor-bank --out BANK --work WORK
python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/bullet-behind-scenery/report.txt \
  --base bench/jit/public/bullet-behind-scenery/defect.patch \
  --candidate bench/jit/public/no-fix.patch \
  --proposal bench/jit/stand-in/bullet-behind-scenery-sensor/jit-proposal.json \
  --out OUT --budget-usd 2 --model off --run-id local-bullet-sensor-stand-in \
  --offer signals-reach-evidence-pixel --withhold-candidate \
  --observer visual-sensor --sensor-bank BANK
```

- `sensor-bank`: 556 templates (408 player, 148 enemy, as before) and the bullet's witness: one
  ring profile, 68 of 68 validation positives matched and 0 of 68 negatives (`met`), `clearPx` 0. Bank digest
  `ee1af0c9c2d8463a8b69ff8d2d831f351ace642e93c006fb0c93d8715e16f1e9`.
- `run`: 5.3 minutes, 15 replays with frames.
  - `shoot-left-every12` was **kept**: it passed the clean game 3 of 3, failed the bug build 3 of 3, and failed
    the bug build with the no-fix patch 3 of 3 (`catch`).
  - `move-fire-right` was **dropped**: the clean game was `needs-review` 3 of 3 (the second bullet is on one
    judged frame of the window, and the coverage rule needs 2: `not-exercised`), while the bug build failed 3
    of 3. Undecided on the clean game, never a failure there.
  - The record's `spendUsd` (0.1662) is its own accounting of the replays at assumed prices. No model was
    called, the sensor reserved $0, and nothing was paid.

What this shows: a no-model pixel check can tell `bullet-behind-scenery` from the clean game on one probe,
three runs each way, judging only bullets drawn alone. What it does not show: that a model proposes such a check (only a live propose
step can show that), or how the witness does on other games.

Earlier runs the same day:
- With the SAM stand-in's full windows all three checks were `needs-review`: fading bullets were on screen in
  those windows on every build.
- With windows ending before the first fading bullet (frames 50 to 80 and 10 to 60) and the first bank
  (`58f45c41...`), both checks were kept. That bank's witness judged bullets beside other ones, which its
  validation had left out; on the whole clean probes it gave `not-found` for 111 clean bullets, every one
  overlapping another bullet. With the crowded rule those windows were `needs-review` on every build, so they
  were cut again as above.
