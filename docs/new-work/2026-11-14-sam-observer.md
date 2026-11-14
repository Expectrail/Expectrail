# SAM 3.1 as the observer the replay asks about pixel checks (#286)

## What changed
- `expectrail/jit/sam_observer.py`: `SamAnchorObserver`, the `sam-3.1-anchor` observer behind the
  replay's `observe` protocol. It asks SAM 3.1 what is drawn inside the player's box where the engine's
  record puts the player, with agents/sam_anchor.py's `anchors` and `measure`. By default the box is the
  logged body box widened by 4 game px; a sized box with a lift is kept for the recorded answers.
- Frames are planned from the route alone (every 10th frame and the last the route fills, at most 30),
  and a replay is refused unless its frames line up: same route name, same frame and physics rates,
  frames numbered from 0 with no hole, and each asked frame's digest matching `replay.json`. Uncaptured
  frames and ticks with no player, camera or body box are gaps (`needs-review`).
- `RecordedSamClient`: gives back a recorded answer file, only for the exact box SAM was asked about.
- `run.py`: an observer that stops part way is charged the images it already sent (`PixelError.images`).
- `pixel.setting_of`: a `--box body` answer file's setting is `{"box": "body", "pad": ...}`; before, the
  string was turned into a list of letters.
- `docs/jit.md`: a section on the observer.

## What was run
- `python3 -m unittest tests.test_jit_sam_observer`: 24 tests, OK. SAM's recorded smoke-route answers
  (run 43337979278) replay through the real observer, on synthetic replay folders built from the
  recording, with the same boxes, answers and holdsPoint on every frame, and the same results (clean
  passes, both layering bugs fail, missing-texture passes, fall-through is needs-review). End to end
  through `run.generate`, the check is kept and a wrong fix caught, 117 images charged.
- Full suite on the branch (main 9dc79d5 plus this change): 3,358 tests, OK, 31 skipped.
- No SAM call, no model call, nothing dispatched.

## Not done
- The command line's `run` and `jit.yml` do not build this observer yet; the reproduction score does
  not count pixel rows.
- No SAM answer on a bench probe. The tests' replays are synthetic, built so the observer asks exactly
  what SAM was asked; they show the plumbing and the frame checks, not SAM's answers on the bench.
- The Godot harness logs the player's `body` box per tick (harness/godot/expectrail_harness.gd) and
  leaves it out when it cannot; whether it is there on every tick of the bench probes was not checked
  on the engine in this change. A tick without one is a gap.

## Files
- `expectrail/jit/sam_observer.py` (new)
- `expectrail/jit/run.py`, `expectrail/jit/pixel.py`
- `tests/test_jit_sam_observer.py` (new)
- `docs/jit.md`, `docs/new-work/2026-11-14-sam-observer.md`
