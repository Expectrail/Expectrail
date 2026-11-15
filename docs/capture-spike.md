# Capture spike: can a supervisor capture Godot frames the game cannot forge? (#246)

**Answer, for this machine and the bundled game:** yes for the frames, no for the trace. A supervisor
that owns the virtual display can grab every frame the game presents, byte for byte equal to the frame
Movie Maker writes, from a folder the game's user cannot open. A rewritten Movie Maker frame then shows
as a mismatch every time. It slows a replay by about 38 %. It does nothing about the trace, which the
game still writes itself, and it cannot stop a game that draws a false picture on the screen in the
first place.

**Recommendation:** implement approach 1 as a follow-up under "After the fund", combined with the
replay sandbox (details at the end). Until it exists, `isolated` stays the top evidence grade and
`protected` stays reserved. No product code changed for this spike.

Everything below was run on November 15, 2026, by builder one, on one Linux machine (Godot 4.7.2,
Mesa llvmpipe, Xvfb, Python 3.13, root, no bubblewrap), on the bundled game and `harness/routes/smoke.json`
(120 frames at 60 fps). No model was called. Not run anywhere else: not on a CI runner, not on macOS,
not on another game.

## How it was run

`python3 -m tools.capture_spike --mode plain|step|sample [--forge] [--reach] --out DIR` (needs root,
Xvfb, setpriv, Godot, NumPy and Pillow). It makes the same copy of the game `harness.run` makes (import
cache, harness autoloads) and runs the same Godot command with Movie Maker on, with three differences:

- **The supervisor owns the display.** The spike starts Xvfb itself with `-fbdir`, so Xvfb keeps its
  screen as a file (`Xvfb_screen0`, XWD format) in a folder of mode 0700 owned by the supervisor's user.
  `-nocursor` is needed: without it Xvfb draws its software cursor into that file, and no grab equals a
  Movie Maker frame.
- **The game runs as another user**: `setpriv --reuid=65534 --regid=65534 --clear-groups
  --no-new-privs`. Its copy, its home and Movie Maker's output belong to that user.
- **The supervisor reads the screen from the file**, crops the game's window (Godot is started with
  `--position 0,0`) and compares each grab with Movie Maker's frames by the SHA-256 of the RGB pixels.

`--forge` adds `forge.gd`, an autoload standing in for a change written to forge its evidence: once
frame 64 is drawn it overwrites Movie Maker's frames 50 to 59 with the bytes of frame 10. `--reach`
makes the game try to read, write, plant a file beside and list the supervisor's screen file.

## Approach 1: the game held after each frame

`step.gd` (an autoload added to the copy) waits after each drawn frame (`RenderingServer.frame_post_draw`)
until the supervisor has grabbed the screen and acknowledged. Godot's `FileAccess` will not open a FIFO
(measured: "cannot open the sync FIFOs"), so the handshake is two ordinary files and polling.

| Run | Wall time | Grabs | Grab equal to Movie Maker's frame at the same index |
| --- | --- | --- | --- |
| step, run 1 | 21.18 s | 120 | 120 of 120 |
| step, run 2 | 19.47 s | 120 | 120 of 120 |
| step, run 3 | 20.22 s | 120 | 120 of 120 |
| step, a second grab 30 ms after the first | 25.11 s | 120 | 120 of 120; the two grabs equal in 120 of 120 |
| step with `--forge --reach` | 20.24 s | 120 | 110 of 120: **frames 50 to 59 differ**, every other frame equal |

- **Aligned to frames:** every grab matched the Movie Maker frame with the same index and no other
  (offset 0 for all 480 grabs of the clean runs). No grab caught a frame half drawn.
- **The game did not behave differently when held:** `trace.json` is byte for byte the same in plain,
  step and sample runs and in a plain `python3 -m harness.run` replay (SHA-256 `0d4f372b90f771bd…`), and
  the grabs of step run 1 equal that replay's own frames, 120 of 120.
- **The forgery is caught every time it is grabbed:** in the forged run the supervisor's grabs 50 to 59
  are the true frames, and Movie Maker's files 50 to 59 are copies of frame 10.

## Approach 2: random grabs, the game not held

The game runs on its own, with nothing added inside it. The supervisor grabs the screen every 5 to
40 ms (random) and afterwards looks for each grab among Movie Maker's frames. A grab is a **frame**
(equal to one), **before** or **after** (outside the first and last matched grab), **torn** (every pixel
from one of the two neighbouring frames: grabbed while the next frame was being put on the screen) or
**unexplained** (between two matched grabs and equal to nothing Movie Maker kept).

| Runs | Wall time | Grabs | frame | before | after | torn | unexplained | Movie frames grabbed at least once |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 clean (seeds 1 to 5) | 15.85 to 16.56 s | 354 to 380 | 321 to 350 | 27 to 30 | 1 to 3 | 0 to 4 | **0** | 120 of 120 in each |
| 5 with `--forge` | 15.37 to 16.68 s | 364 to 388 | 306 to 324 | 25 to 30 | 2 to 3 | 0 to 4 | **27 to 29**, all between frames 49 and 60 | 120 of 120 in each |

- It needs nothing inside the game, so the game has no handshake to lie through.
- It caught the ten forged frames in all five runs, but as a stretch ("something between frames 49
  and 60 is not what was drawn"), not frame by frame.
- Grabs tear. 9 of the 10 runs had 1 to 4 torn grabs. The edge of a tear is ragged (some grabs
  top-down, some bottom-up, with steps of 7 to 14 pixels within a row), so the tear test can only ask
  that every pixel comes from one of the two neighbours. A forged picture built from two neighbouring
  frames would pass as a tear.
- Each frame was grabbed about three times here only because Movie Maker's PNG encoding slows the game
  to about 8 frames a second. A game that runs faster gets fewer grabs a frame, and a one-frame forgery
  could fall between grabs. That was not measured.
- About 28 grabs a run come before Movie Maker's first frame: a blank screen, then pictures the window
  showed before recording began. They say nothing either way.

## What the game's user could reach

Tried from inside the game (GDScript in `forge.gd`, `--reach`) and from a process of the game's user:

| Attempt | Result |
| --- | --- |
| read the screen file (GDScript) | refused ("Can't open file") |
| write the screen file (GDScript) | refused ("Can't open file") |
| plant a file beside it (GDScript) | refused ("Can't open file") |
| list the capture folder (GDScript) | refused ("Invalid parameter") |
| read, write, list, plant (process of uid 65534) | refused (Permission denied) each |
| signal the display server | refused (Operation not permitted) |
| read the display server's memory (`/proc/<pid>/mem`) | refused (Permission denied) |

**Not measured:** that the game, as an X client, can read the screen through X (any X client can; it is
its own picture) or draw outside its window; whether a malicious client can crash or take over Xvfb.

## Approach 3: other documented ways

Only one was used: Xvfb's own `-fbdir` (from `Xvfb -help` on this machine: "-fbdir directory  put
framebuffers in mmap'ed files in directory", and "-nocursor  disable the cursor"). It makes the screen a
file the supervisor reads without being an X client. No further search of Godot's or Mesa's
documentation was done this run.

## Slowdown

| Mode | Wall time, mean | Against plain |
| --- | --- | --- |
| plain (game as uid 65534 on the supervisor's display), 3 runs | 14.68 s (14.42 to 15.05) | |
| approach 1, 3 runs | 20.29 s (19.47 to 21.18) | +38 %, a median hold of 23 to 26 ms a frame |
| approach 1 with a second grab 30 ms later, 1 run | 25.11 s | +71 % |
| approach 2, 5 clean runs | 16.28 s (15.85 to 16.56) | +11 % |

The hold is mostly reading the 8 MB screen file and decoding it in Python; cropping straight from a
memory map would shorten it. Not tried.

## What this does not settle

1. **The game draws the picture.** A display capture shows what the game put on the screen. A change
   written to show a false picture (a recorded frame drawn over the level, say) shows it on the screen
   too, and the supervisor grabs it faithfully. What the capture removes is the gap between what was
   shown and what the files say: frames rewritten after the fact, frames from another run, frames that
   were never shown. The visual observer judges what is on the screen either way.
2. **The handshake runs inside the game.** In approach 1 the game says when a frame is drawn. A forging
   game could skip or fake it. The product's rule would have to be: exactly one grab per frame the route
   implies, each equal by content to Movie Maker's frame of the same index; anything else is "cannot
   tell", never a pass. Approach 2 has no handshake and could check approach 1's grabs from outside.
3. **The trace is still the game's.** "A forged trace" stays open in `docs/release-gate.md`. This spike
   does nothing for it.
4. **Separate user, not the sandbox.** The separation here was `setpriv` as root. The product's sandbox
   is bubblewrap without root, and it starts the display inside the sandbox today (`harness/sandbox.py`).
   The design that follows from this spike moves Xvfb out to the supervisor and binds only its socket
   into the sandbox, so the capture folder is not in the game's view at all, and runs Xvfb as a user
   other than the judge's, since a client that took over the X server would hold the capture. Not run:
   bubblewrap cannot be installed on this machine.
5. One machine, one game, one route, software rendering. A CI runner, a GPU or Vulkan renderer, a
   faster game and a longer route are not measured.

## Follow-up

If Sean agrees, an issue under "After the fund": "Protected capture: a supervisor-owned display for
the replay sandbox". Built from approach 1 (held frames, grabs compared byte for byte with Movie Maker's,
the rule in point 2), with approach 2's classifier as a cross-check, run in CI's `release-gate` job where
bubblewrap exists, and the "a rewritten frame" row of the release gate held by it. Until that is built
and measured there, the check keeps refusing `protected`.

## Files

- `tools/capture_spike/spike.py`: the supervisor, the three modes and the comparison.
- `tools/capture_spike/step.gd`: the hold after each frame (approach 1), added only to the spike's copy.
- `tools/capture_spike/forge.gd`: the stand-in forger and the reach attempts.
- `tests/test_capture_spike.py`: the screen-file reader, the tear test, the grab classifier and the
  step summary, on made-up pixels.
