# The bullet capture for `bullet-behind-scenery`, remade with the windows: the asking job now reserves 675 images and asks (#286)

## What changed
The committed capture record of the three hand-written `visible` bullet checks
(`bench/jit/stand-in/bullet-behind-scenery-visible/jit-run.json`) was made on November 17, before #605, when the
capture kept every planned frame and `pixel-ask` refused at jit.yml's $2 cap. It is replaced by a capture made
on current main (5aa941f) with the windows. The new record differs from the old only in the mechanics
profile's hash (`menuActions`, #622) and the replay time, so the capture's spend is $0.1987, not $0.2089.
The stand-in's README and `docs/jit.md` record the run, and a new test pins what `pixel-budget` gave
(1.8013) and what `pixel-ask` reserved (675 images, $1.6875) from the committed record and plan.

## What was run
- `jit run --proposal ... --observer sam-3.1-anchor --pixel-capture CAPTURE` (the command on the stand-in's
  page), Godot 4.7.2-stable from `harness/get_godot.sh`, under `xvfb-run`, in a 2-CPU cloud container:
  `status: complete`, 27 replays, 9 min 16 s. The capture kept 225 frames (49 MB, not committed).
- `pixel-budget --record OUT/jit-run.json --budget-usd 2`: `1.8013`.
- `pixel-ask --replays CAPTURE --budget-usd 1.8013 --sam-answers tests/data/sam-anchor/bundled-lift-14.json`:
  `"asked": true, "plannedImages": 675, "calls": 0`, stopped at the first replay because the recorded answer
  file was asked under another setting. Nothing was sent anywhere.
- `python3 -m tools.bullet_visible_stand_in --measure CAPTURE`: rewrote `capture-plan.json` identical to the
  committed one (no diff).
- The new test fails on the November 17 record and passes on the new one.
- Full suite on main 5aa941f plus the change, with the engine present (`xvfb-run python3 -m unittest discover -s tests -t .`): 5,048 tests, OK, 39 skipped, 19.5 minutes.
- No model, no SAM call, no dispatch, nothing spent.

## Not done
SAM has not been asked about these frames (`pixel-ask --sam-live`, at most $1.69 at list price), and the
judging step (`run --pixel-replays`) has not been run. That needs Sean.

## Files
- `bench/jit/stand-in/bullet-behind-scenery-visible/jit-run.json`
- `bench/jit/stand-in/bullet-behind-scenery-visible/README.md`
- `docs/jit.md`
- `tests/test_bullet_visible_stand_in.py`
- `docs/new-work/2026-11-18-bullet-recapture-windows.md`
