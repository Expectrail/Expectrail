# A hand-written `visible` bullet stand-in for `bullet-behind-scenery`, for SAM (#286)

**No model wrote these checks, and SAM has not been asked about them.** They are not a reproduction, and the
reproduction score gives a record made from them no result (`expectrail/repro/score.py`, `STAND_INS`).

`bullet-behind-scenery` changes the bullet's `z_index` from 5 to -5, so the bullets are drawn behind the
scenery. Nothing in the engine's record changes. The no-model sensor cannot be asked about the bullet: its
bank holds no bullet template (the bullet's additive glow gives no crop with enough opaque detail). So these
checks name `sam-3.1-anchor`, asked at each bullet's logged box.

- `jit-proposal.json`: three `visible` checks about the bullet, `minFraction` 1.0, written by
  `python3 -m tools.bullet_visible_stand_in --out <dir>`. Made under `signals-reach-evidence-pixel` with the
  candidate withheld, so it is bound to the bench's report and to no patch.

  | Probe | Window | Planned frames in it |
  | --- | --- | --- |
  | `shoot-left-every12` | from frame 50 | 9 |
  | `move-fire-left` | from frame 90 | 8 |
  | `move-fire-right` | frames 10 to 80 | 8 |

- `capture-plan.json`: on each planned frame of each captured replay, how many bullets the engine logged on
  screen. Written by `python3 -m tools.bullet_visible_stand_in --measure <capture folder>`. The tool refuses
  a window that holds a frame with more than 3 bullets on screen, or none on the clean game.
- `jit-run.json`: the capture run's record. `jit run --proposal --pixel-capture`, on the real engine, on
  November 18, 2026, with the windows (#605). Every pixel check is `not-run`, waiting for the asking job.

## The run

Godot 4.7.2-stable (`harness/get_godot.sh`), Xvfb, a cloud container with 2 CPUs, no model key and no SAM key
in the environment.

```
python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/bullet-behind-scenery/report.txt \
  --base bench/jit/public/bullet-behind-scenery/defect.patch \
  --candidate bench/jit/public/no-fix.patch \
  --proposal bench/jit/stand-in/bullet-behind-scenery-visible/jit-proposal.json \
  --out OUT --budget-usd 2 --model off --run-id local-bullet-visible-stand-in \
  --offer signals-reach-evidence-pixel --withhold-candidate \
  --observer sam-3.1-anchor --pixel-capture CAPTURE
python3 -m expectrail.jit.cli pixel-budget --record OUT/jit-run.json --budget-usd 2
python3 -m expectrail.jit.cli pixel-ask --replays CAPTURE --out answers.json --budget-usd 1.8013 \
  --sam-answers tests/data/sam-anchor/bundled-lift-14.json
python3 -m tools.bullet_visible_stand_in --measure CAPTURE
```

**November 18 (the committed record).** The capture took 9.3 minutes: 27 replays, 3 probes, 3 builds, 3 runs
each. It kept 225 frames, 49 MB, which are not committed: the planned frames inside the windows only. The
record's spend, $0.1987, is its own accounting at assumed prices. No model was called, nothing was paid, and
SAM was asked about 0 images.

`pixel-budget` gave the asking job $1.8013: the $2 cap less the capture's spend. `pixel-ask` reserved the
images and did not refuse:

```
{"asked": true, "runs": 0, "replays": 27, "plannedImages": 675, "calls": 0, "usd": 0.0, "usdPerImage": 0.0025,
 "stopped": "pixel-reference/move-fire-left-1: the recorded answers were asked with {\"lift\": 14.0, \"model\": \"sam-3.1\"}, and this observer asks with {\"box\": \"body\", \"lift\": 0.0, \"model\": \"sam-3.1\", \"pad\": 4.0}"}
```

675 images is 25 planned frames inside the windows (9, 8 and 8) on each of 9 replays, 3 images a frame. The
recorded answer file only stands in for a SAM client: it was asked under another setting, so the asking job
stopped at the first replay and sent nothing. That stop is the guard working, not an answer about the bullet.
`--measure` on this capture wrote a `capture-plan.json` identical to the committed one.

The record differs from the November 17 capture's in two places: the mechanics profile's hash (it gained
`menuActions` in #622) and the replay time, hence the spend. Every check, window and count is the same.

**November 17 (before #605).** The first capture kept every planned frame of the three probes, 86 MB, at a
spend of $0.2089. With the asking job's $1.7911, `pixel-ask` refused, and nothing was asked:

```
{"asked": false, "reason": "the 27 replays need up to 1296 images, $3.2400, over the budget of $1.79; nothing was asked"}
```

## What the frames show

On every captured replay, the engine logged the same bullets on the clean game, the bug build and the bug
build with the no-fix candidate. On the clean game the bullets are drawn. On the bug build they are not drawn
where the engine puts them: on frame 60 of `move-fire-left`, the clean game draws cyan bullets at the wall
and the bug build draws none there. These numbers are from the first capture, of the whole probes, which
`capture-plan.json` was measured on first; the second capture, with the windows, gave the same plan. Inside the bullets' prompt boxes on the planned frames, most of the box's
pixels differ between the two builds (for example 2,401 of 2,401, and 1,903 of 2,401, on frame 70 of
`move-fire-left`). Whether SAM finds a bullet in either picture is untested.

## What this shows and what it does not

It shows that the capture job, run by `jit run` itself on the real engine, captures pixel checks about the
bullet, and that since #605 it keeps only the windows' frames. It shows that the asking job, given jit.yml's
default cap, now reserves the 675 images these three checks need ($1.69 of $1.80) and goes on to ask.

It does not show that SAM sees the difference, or that the keep rule keeps any of these checks. That needs
the asking step with SAM's key (`pixel-ask --sam-live`, at most $1.69 at list price) and then the judging
step (`run --pixel-replays`).
