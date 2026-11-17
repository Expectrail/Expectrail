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
  November 17, 2026. Every pixel check is `not-run`, waiting for the asking job.

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
python3 -m expectrail.jit.cli pixel-ask --replays CAPTURE --out answers.json --budget-usd 1.7911 \
  --sam-answers tests/data/sam-anchor/bundled-lift-14.json
```

The capture took 10.5 minutes: 27 replays, 3 probes, 3 builds, 3 runs each. It kept 86 MB of frames, which
are not committed. The record's spend, $0.2089, is its own accounting at assumed prices. No model was called,
nothing was paid, and SAM was asked about 0 images.

`pixel-budget` gave the asking job $1.7911: the $2 cap less the capture's spend. `pixel-ask` refused, and
nothing was asked:

```
{"asked": false, "reason": "the 27 replays need up to 1296 images, $3.2400, over the budget of $1.79; nothing was asked"}
```

The recorded answer file is only there to build the observer. The refusal comes before any answer is read.

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
bullet. It also shows that the asking job, given jit.yml's default cap, would ask SAM nothing about these
three checks. The asking job plans every 10th frame of each probe's route whatever the checks' windows, so
the windows above do not lower the reservation. One check on one probe fits the cap; three do not.

It does not show that SAM sees the difference, or that the keep rule keeps any of these checks. That needs
the asking step with SAM's key, a budget of at least $3.24, and then the judging step (`run --pixel-replays`).
