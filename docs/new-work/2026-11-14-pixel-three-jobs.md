# Pixel checks across three jobs: capture, ask, judge (#286)

## What changed
- `expectrail/jit/pixel_jobs.py` (new): pixel checks split into three jobs, so SAM's key and the
  change's code never meet, as jit.yml already does for the model.
  1. **Capture**: `run --observer sam-3.1-anchor --pixel-capture DIR` replays each pixel check's probe
     with frames on the clean game, the bug build and the candidate, 3 times each, and keeps the
     folders in `DIR/<build>/<probe>-<n>/` with the route each replayed. It asks nothing; the pixel rows
     are `not-run` with the reason `CAPTURED`. It refuses `--sam-answers`, `--sam-live` and `--sam-run`.
  2. **Ask**: `pixel-ask --replays DIR --out answers.json --budget-usd X` with `--sam-live`, or with
     `--sam-answers` to rehearse. It runs no game. It plans every stored replay's frames from its route
     and reserves all their images against the budget before the first request. Over the budget, it
     sends nothing and exits 1. It asks through the same `SamAnchorObserver` the judge uses, and writes
     an agents/sam_anchor.py answer file with one run per replay, named `<build>/<probe>-<n>`. The first
     replay that cannot be asked about stops the asking (`stopped`); what was sent is counted.
  3. **Judge**: `run --observer sam-3.1-anchor --sam-answers answers.json --pixel-replays DIR`. Trace
     checks replay as before. A pixel replay is the captured folder (`StoredReplays`), used only if
     its route equals the route this run compiled; otherwise the run ends as nothing generated. A
     replay missing from the answers, answers asked another way, or a frame changed since capture
     drops the check. `--pixel-replays` refuses `--sam-live`.
- The capture folder is treated as untrusted: only the three build names, `<probe>-<n>` folders and
  regular files are accepted, with no symbolic link and at most 36 replays.
- `expectrail/jit/run.py`: `generate(..., pixel_capture=DIR)` and `_pixel_capture`.
- `expectrail/jit/cli.py`: `--pixel-capture`, `--pixel-replays`, the `pixel-ask` command, and the
  observer arguments each job may take. Docstrings in `cli.py`, `run.py` and `sam_observer.py`.
- `docs/jit.md`: a section on the three jobs.
- No contract changed. The capture folder holds replay folders and routes in their existing formats.
  The answer file is agents/sam_anchor.py's existing format, read by `RecordedSamClient`.

## What was run
- `python3 -m unittest tests.test_jit_pixel_jobs`: 18 tests, OK (31 s). Through `cli.main`, with the
  simulated game and a test transport, the three jobs give the one-job result:
  - a wrong fix is kept and caught (clean pass ×3, bug fail ×3, candidate fail ×3, 117 images charged);
  - a good fix is not caught;
  - the asking step runs no game;
  - the judging step makes no frames.

  The refusals are tested one by one. SAM's answers are the recorded smoke-route answers
  (tests/data/sam-anchor/), given through `--sam-answers`. The replay folders are synthetic.
- Full suite on the branch merged with main 6716b9e (`python3 -m unittest discover -s tests -t .`):
  3,464 tests, OK, 31 skipped.
- No SAM call, no model call, nothing dispatched, nothing spent.

## Not done
- jit.yml does not run the three jobs. The asking job needs SAM's key (`MODEL_API_KEY`) in the
  `main-only` environment, and only Sean may give a job a secret.
- The capture folder keeps every frame of each replay, not only the planned ones. For long routes the
  artifact could be large. That is not measured.
- No SAM answer on a bench probe, and no reproduction rate with pixel checks.

## Files
- `expectrail/jit/pixel_jobs.py`
- `expectrail/jit/run.py`
- `expectrail/jit/cli.py`
- `expectrail/jit/sam_observer.py`
- `tests/test_jit_pixel_jobs.py`
- `docs/jit.md`
- `docs/new-work/2026-11-14-pixel-three-jobs.md`
