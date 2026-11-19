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
  | `shoot-left-every12` | frames 50 to 80 | 4 |
  | `move-fire-right` | frames 10 to 60 | 6 |

  The windows are the SAM stand-in's (`../bullet-behind-scenery-visible/`), cut short: the sensor does not
  judge a bullet in its fade (the last 0.3 s of its life; a gap), and on the clean game's replay every planned
  frame from frame 90 of `shoot-left-every12` and from frame 70 of `move-fire-right` has a fading bullet on
  screen. `move-fire-left` has a fading bullet on all but one planned frame of its SAM window, so it is left
  out.
- `jit-run.json`: the run's record (below).

## The run

Godot 4.7.2-stable (`harness/get_godot.sh`), Xvfb, a cloud container with 2 CPUs, no model key and no SAM key
in the environment. November 19, 2026, on main 8c2f9a2 plus the change.

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

- `sensor-bank`: 8 minutes. 556 templates (408 player, 148 enemy, as before) and the bullet's witness: one
  ring profile, 70 of 70 validation positives matched and 0 of 70 negatives (`met`). Bank digest
  `58f45c4190bd374bbf6bc4449a6fa35dbcb21cb529b74898a161db3fdeec797c`.
- `run`: 7.8 minutes, 18 replays with frames. Both checks were **kept**: each passed the clean game 3 of 3 and
  failed the bug build 3 of 3, and failed the bug build with the no-fix patch 3 of 3 (`catch`). The record's
  `spendUsd` (0.1857) is its own accounting of the replays at assumed prices. No model was called, the sensor
  reserved $0, and nothing was paid.

What this shows: a no-model pixel check can tell `bullet-behind-scenery` from the clean game on these two
probes, three runs each way. What it does not show: that a model proposes such a check (only a live propose
step can show that), or how the witness does on other games.

An earlier run the same day with the SAM stand-in's full windows dropped all three checks as `needs-review`:
fading bullets were on screen in those windows on every build. That is why the windows above are shorter.
