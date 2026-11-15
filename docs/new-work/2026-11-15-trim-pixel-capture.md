# The pixel capture folder keeps only the frames the observer asks about (#286)

## What changed
Under the pixel setting, replay-final keeps every pixel check's replays for pixel-ask and pixel-judge
(`--pixel-capture`). Until now each replay folder was copied whole: every frame Movie Maker wrote, the
sound file, the Godot log and the game's working copy. Measured on two bench probes (below), a folder is
39.5 MB (hold-right) to 113.1 MB (wait-long), and a change can keep up to 36 of them, so one case's
`-captured` artifact could reach about 4 GB, uploaded once and downloaded twice.

- `pixel_jobs.store_replay` now keeps only `replay.json`, `trace.json`, the route and the frames the
  observer plans for the route (`observer.frames(route)`, at most 30). `run._pixel_capture` passes the
  observer's plan. A probe the observer cannot plan for is not replayed, as the judging run would not
  run its checks either.
- `pixel_jobs.replays` and `StoredReplays` accept a replay folder only if it holds just that: the two
  records, the route, and `frames/f<8 digits>.png` files. Anything else refuses the folder.
- `SamAnchorObserver` accepts a kept replay. The frames on disk must be numbered below the replay's
  count, with a digest for each frame counted, and **every frame it asks about must be there**: a kept
  replay missing a planned frame is refused, so trimming can never turn a question into a gap. A full
  replay with a missing frame that is asked about is refused as before (same message start). A full
  replay missing a frame that is never asked about is now accepted; that frame was never looked at.
  Each asked frame is still checked against its digest in `replay.json`.
- `docs/jit.md` says what a kept replay holds.

## What was run
- The measurement, on this container (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb, llvmpipe):
  two library probes replayed with frames on the clean game through `harness.run.run(capture_frames=True)`,
  then kept with the new `store_replay` and the default `sam-3.1-anchor` plan:

  | probe | ticks | frames | planned | full folder | kept folder |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | wait-long | 1150 | 575 | 30 | 113.1 MB | 6.19 MB |
  | hold-right | 340 | 170 | 18 | 39.5 MB | 3.81 MB |

  Of the full folder, the frames were 104.0 and 33.5 MB and the working copy 4.6 MB. A frame is about
  180 to 200 KB at 1600 x 960. On both, the observer (with a stand-in client, no SAM call) gave the same
  answer and asked the same number of images on the full and the kept folder. Worst case for one case,
  36 replays of a 30-frame probe: about 223 MB instead of about 4.1 GB.
- `python3 -m unittest tests.test_jit_pixel_trim tests.test_jit_pixel_jobs tests.test_jit_sam_observer
  tests.test_jit_pixel_workflow`: 72 tests, OK.
- `python3 -m unittest discover -s tests -t .` on the branch (main 7ed6106 plus the change): 3,829 tests,
  OK, 22 skipped (fewer skips than usual because this container had Godot). After that run, only an
  import was reordered and a lint comment changed; the four pixel test modules were run again: OK.

Nothing was dispatched and nothing was spent: no model call, no SAM call.

## Not done
- No live run of the pixel setting yet (#286 waits on Sean for it). The kept folder's size in CI is not
  measured; the numbers above are from this container's renderer.
- `trace.json` is kept whole (0.25 to 0.71 MB); it is small next to the frames, so it is left as is.

## Files
- `expectrail/jit/pixel_jobs.py`
- `expectrail/jit/run.py`
- `expectrail/jit/sam_observer.py`
- `tests/test_jit_pixel_trim.py`
- `docs/jit.md`
- `docs/new-work/2026-11-15-trim-pixel-capture.md`
