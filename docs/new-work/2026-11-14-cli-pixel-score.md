# The command line's run builds the SAM observer, and the score counts pixel checks on their own (#286)

## What changed
- `expectrail/jit/cli.py`: `run` takes the pixel setting (`--offer signals-reach-evidence-pixel`) and an
  observer for its pixel checks (`observer_from`). `--observer none` (the default) leaves them `not-run`;
  `--observer sam-3.1-anchor` needs exactly one of `--sam-answers FILE` (recorded answers through
  `RecordedSamClient`; `--sam-run BUILD=RUN` picks the recorded run for a replay build) or `--sam-live`
  (a live call: spends money, never run here). `--sam-box`, `--sam-pad`, `--sam-lift`, `--sam-first` set
  how SAM is asked. Every wrong combination exits 2 before anything runs.
- `expectrail/jit/offer.py`: `SCORED` (every setting). The workflow's list (`OFFERS`) is unchanged.
- `expectrail/repro/score.py` and `contracts/repro-score.v1.schema.json`: the score takes the pixel
  setting. A pixel check reproduces by the bench's rule, read from its own runs (`pixel.kept_rows`, then
  3 of 3 failing with the no-fix candidate). A row's counts include pixel checks; its `pixel` object and
  the totals' `pixel` give the pixel share (defects a pixel check reproduced, and those only a pixel check
  did). A pixel row whose status or outcome its runs contradict gives no result. `--screen` (any setting)
  puts the screen record's measurement on each row and gives the rate on the screen-only defects apart.
  New fields are optional, so earlier score records still read. Example:
  `contracts/examples/repro-score-pixel.json` (made-up rows).
- `expectrail/repro/__main__.py`: `score --offer` takes every setting; `score --screen PATH`.
- `docs/jit.md`, and the docstrings of `pixel.py`, `sam_observer.py` and `offer.py`: what is wired now.

## What was run
- `python3 -m unittest tests.test_jit_cli_observer tests.test_repro_score_pixel`: 31 tests, OK. End to end
  through `cli.main(["run", ...])` with the observer the command line built from SAM's recorded
  smoke-route answers (tests/data/sam-anchor/): a wrong fix is caught (kept 3/3 and 3/3, catch, 117
  images charged), a good fix is not, and an observer asked otherwise than the recording drops the
  check with that reason and charges nothing. The engine and the model are the test stand-ins.
- `score --offer signals-reach-evidence-pixel --screen bench/jit/public/screen.json` on an empty records
  folder (the real bench): exit 0, screen-only 2 (as the committed screen record says), no result 24.
- Full suite on the branch (main cb1fc85 plus this change): 3,413 tests, OK, 31 skipped.
- No SAM call, no model call, nothing dispatched, nothing spent.

## Not done
- `jit.yml` does not take the pixel setting: its replay jobs capture no frames and hold no SAM key, and
  the key must not meet the change's code. The likely shape is a job that asks SAM about frames the
  replay uploaded; adding the key to any job is Sean's to do.
- No SAM answer on a bench probe, and no reproduction rate with pixel checks.

## Files
- `expectrail/jit/cli.py`, `expectrail/jit/offer.py`, `expectrail/jit/pixel.py`, `expectrail/jit/sam_observer.py`
- `expectrail/repro/score.py`, `expectrail/repro/__main__.py`
- `contracts/repro-score.v1.schema.json`, `contracts/examples/repro-score-pixel.json`
- `tests/test_jit_cli_observer.py`, `tests/test_repro_score_pixel.py`, `tests/test_jit_offer.py`,
  `tests/test_jit_pixel_replay.py`
- `docs/jit.md`, `docs/new-work/2026-11-14-cli-pixel-score.md`
