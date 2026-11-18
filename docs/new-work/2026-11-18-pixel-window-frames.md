# The observer is asked only about the frames inside the checks' windows (#605, for #286)

## What changed
A pixel check judges only the planned frames in its window, but SAM was asked, and paid, for every planned
frame of the probe's route (every 10th frame). Now all four places plan the observer's frames as its plan
inside the union of the windows of the checks on that probe (`pixel.planned`, `pixel.probe_windows`,
`pixel.in_windows`); a check without a window keeps the whole plan:

- **In-process replay** (`run.py`, `_pixel_plans` then `_pixel_stage`): the reservation is
  `most_images(..., windows=...)`, and the observer is asked with the windows.
- **Capture** (`_pixel_capture`, `pixel_jobs.store_replay`): keeps only the windows' frames and writes the
  windows beside the replay as `windows.json`.
- **Asking job** (`pixel_jobs.ask`): reads `windows.json` back as untrusted data (`windows_of`: 1 to 4
  windows of whole frames from 0, each once, nothing else) and reserves and asks only those frames.
- **Judging job**: plans the same frames from the proposal's checks; recorded answers planned for other
  windows are refused by `RecordedSamClient.plan_of`, so the checks are dropped, never passed.

Both observers (`sam-3.1-anchor`, `visual-sensor`) take `windows`, and `pixel.observe` refuses an answer
whose frames are not the windows' planned frames. A check whose window holds no planned frame is `not-run`
(`pixel.NO_PLANNED_FRAME`) and asks for nothing; a probe left with no check is not replayed.
`tools/bullet_visible_stand_in.py` now reserves the windows' frames (`reserved_images`: 675) and `measure` reads
a capture that kept only them.

No JSON schema covers the capture folder's files (`objects.json` has none either); the writer
(`store_replay`) and the reader (`windows_of`) are in this change, and the answer file's `framesProbed` is
unchanged in shape.

## What was run
- `python3 -m unittest tests.test_jit_pixel_windows`: 25 tests, OK. Among them: the bullet stand-in's three
  checks reserve 675 images ($1.6875) in `pixel-ask` and in the in-process reservation; the judging run
  drops a check whose answers were planned for the whole route; a window with no planned frame is not run
  in the capture or in the in-process replay.
- `python3 -m unittest tests.test_bullet_visible_stand_in`: 26 tests, OK.
- The full suite on the branch: see the pull request for the count and result.
- Nothing was dispatched; no model and no SAM call; no game was run outside the simulated one in the tests.

## Not done
- The bullet probes were not captured again with the windows, and `pixel-ask` was not run on a real capture.
- The SAM asking step on the bullet checks (#286) still needs Sean: now at most $1.69 at list price.

## Files
- `expectrail/jit/pixel.py`, `expectrail/jit/run.py`, `expectrail/jit/pixel_jobs.py`,
  `expectrail/jit/sam_observer.py`, `expectrail/jit/template_observer.py`, `expectrail/jit/cli.py` (docstring)
- `tools/bullet_visible_stand_in.py`
- `tests/test_jit_pixel_windows.py` (new), `tests/test_bullet_visible_stand_in.py`
- `docs/jit.md`, `bench/jit/stand-in/bullet-behind-scenery-visible/README.md`
