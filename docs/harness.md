# Harness

The harness turns a route into frames a model can look at, the same way every time.

```sh
./harness/get_godot.sh                                   # Godot 4.7.2, checked against its SHA-512
python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke
python3 -m harness.run --route harness/routes/smoke.json --out runs/fall \
  --patch bugs/physics-fall-through/v1.patch             # with a seeded bug
python3 -m harness.run --route harness/routes/smoke.json --out runs/fixed \
  --patch bugs/physics-fall-through/v1.patch \
  --patch agents/fixtures/fix-collision-mask.patch     # seed then candidate (repeatable --patch)
python3 -m harness.replay_check --route harness/routes/smoke.json --runs 10

# Or run fully containerized (Docker / Linux container):
./harness/docker_run.sh                                  # 10-run replay check inside container
./harness/docker_run.sh python3 -m harness.run --route harness/routes/smoke.json --out runs/container-smoke
```

How it works:

1. It copies `game/platformer` to `<out>/work`, applies one or more patches in order (seed, then
   candidate), and adds `expectrail_harness.gd` to the copy as an autoload. The game in the
   repository never changes. Base asset imports are cached (`tools/godot_cache/.godot`), so clean
   runs skip the full-project re-import. The cache is keyed to the exact Godot binary and game files
   (`tools/godot_cache/.godot.key`) and is rebuilt when either changes; an import folder inside
   `game/platformer` (from the editor or a local play session) is never used. Frames are identical
   with and without the cache.
2. It imports any newly patched assets incrementally, then runs it under a virtual display
   (`xvfb-run`) with the Compatibility renderer on software OpenGL (Mesa llvmpipe). `--headless`
   cannot be used for capture: it does not render.
3. Godot's Movie Maker mode (`--write-movie`, `--fixed-fps 60`, `--disable-vsync`) writes every
   frame to a PNG. It runs in non-real time, so a slow machine produces the same frames, more
   slowly, instead of dropping them.
4. The autoload presses and releases input actions on the exact physics ticks the route names, before
   any game node runs that tick, and a second node records the player's position after every node
   has moved. It writes `trace.json` and quits when the route ends. Besides the player's position,
   each row records which way the robot's sprite faces, where every enemy and every bullet is, the
   ground line under the player, the coins and the camera; the header comment of
   `harness/godot/expectrail_harness.gd` lists every field. Recording facing, enemies and bullets
   (added October 30 for the engine-record checks in `agents/trace_checks.py`) does not change a
   frame: 0 of 120 smoke frames differ from a run without it. Since October 31 the enemies and the
   bullets are written on every tick, an empty list when there are none, and the trace's header
   declares what the recorder collects (`capabilities`), so advisory discovery can tell "none
   there" from "not recorded". That change also leaves every smoke frame unchanged.
5. `replay.json` records the route, the game tree digest, the patch, the engine and device, and the
   sha256 of every frame.

**Trace-only replays (October 31).** Advisory discovery reads the trace, not the frames, so it calls
`harness.run.run(..., capture_frames=False)`: Godot runs `--headless` with the same fixed frame rate
and writes no PNGs, about four times faster. The physics is identical: on the same route and patch,
the trace rows match the captured run's tick for tick, except the camera's view transform, which no
discovery contract reads. The verifier always captures frames.

## What we measured on day one (October 26)

On a 2-core cloud container with no GPU (Mesa llvmpipe, LLVM 20), Godot 4.7.2:

- The demo renders correctly under Xvfb; a 240-tick route (2 seconds of game time, 120 frames)
  takes about 20 to 30 seconds including import, most of it PNG encoding.
- Ten runs of the smoke route produced bit-identical frames and identical player traces. That
  settles replay on one machine and one binary only: frames from a GPU machine will differ, so
  evidence and baselines must come from the same runner type.
- The seeded fall-through bug (`bugs/physics-fall-through/v1.patch`) shows the player below the
  ground line from about frame 8 to frame 20, then off screen. Ten runs with the bug were also
  bit-identical, so the failure reproduces the same way every time.

Not settled yet: the input driver for gamepad-style analog input (routes only press actions), and
resetting mid-run (each run starts the game fresh, which takes a few seconds).

## Flaky routes and baselines (November 9)

Determinism was measured on one machine, so a failure seen once may not be a failure.
`agents/stability.py` replays a route several times before a failure counts:

```sh
python3 -m agents.stability --route harness/routes/smoke.json \
  --patch bugs/physics-fall-through/v1.patch --out runs/stability [--runs 3] [--record-baseline]
```

- It replays the route 3 times by default, the same three-of-three rule advisory discovery uses,
  and compares the replays by the `frameSha256` list and the trace sha256 in `replay.json`. Each
  replay is judged; the command line uses the verifier's ground check on the position log, with no
  SAM images.
- `stable-fail` (every replay identical, every one failed) stays a failure, and `stable-pass` stays
  a pass. `flaky` means the replays differ, the judged results differ, some replays did not run, or
  identical replays differ from this machine's baseline: it is needs-review, never a pass and never
  a fail. `undecided` (nothing ran, or the judge could not decide) is needs-review too.
- The report, `stability.json` (`expectrail.stability/v0`), records a machine fingerprint: the CPU
  model from `/proc/cpuinfo`, the Mesa version Godot printed in `godot.log`, and the engine version,
  renderer and device from `replay.json`. `replay.json` is unchanged, because `harness/run.py` is
  pinned.
- Hash-only baselines, one file per fingerprint, live in [`bench/baselines/`](../bench/baselines/README.md).
  Only `--record-baseline` writes them.

`python3 -m agents.loop --stability` replays the failing route on the failing base before the fixer
starts, and sends only a stable failure to the fixer; anything else stops the run as needs-review
before Muse Code is called. `python3 -m agents.heldout_bench --stability` replays every route where a
check failed and keeps a check's result only when it held on every identical replay. Both flags are
off by default, so recorded results stay as they were: with them on, every failing route costs two
more replays, the bench sends SAM those replays' frames when SAM is on, and the loop needs Godot even
when it verifies from fixtures. The verifier still replays each route once.

On November 9, on a 2-core cloud container with no GPU (Intel Xeon @ 2.10GHz, Mesa 25.2.8 llvmpipe,
Godot 4.7.2), the smoke route with `bugs/physics-fall-through/v1.patch` was a stable fail in three
separate runs of three replays, all nine identical, and the clean smoke route was a stable pass.

## Seeded bugs must be visible

```sh
python3 -m harness.check_seeded            # replays every bugs/<family>/v*.patch against the clean route
```

Each seeded variant must change at least one frame compared with the clean game; otherwise it is a
bug nobody could see, and the benchmark would count it as a miss. CI runs this as `seeded-bugs`.

## Routes

Routes (`expectrail.route/v0`) define exact sequences of physics ticks and input actions to replay deterministically across clean and patched builds:

| Route | File | Ticks | Description |
| :--- | :--- | :--- | :--- |
| `smoke` | `harness/routes/smoke.json` | 240 | Basic forward movement and two jumps (quick pipeline sanity check). |
| `coins` | `harness/routes/coins.json` | 240 | Traverses ground coin clusters, jumps into the coin arc, and verifies coin pickup and visibility. |
| `combat` | `harness/routes/combat.json` | 180 | Forward movement with weapon fire (`shoot`) against the enemy patrol, leap avoidance, and stop. |
| `traversal` | `harness/routes/traversal.json` | 360 | Vertical traversal across elevated and one-way platforms, exercising camera tracking and player layering. |

The reported bugs bring their own routes, in `bugs/reported/routes/` (listed in `bugs/reported/manifest.json`):

| Route | Ticks | Description |
| :--- | :--- | :--- |
| `climb-gap` | 600 | Walk under the gap in the platforms above, press jump ten times, wait to land (`air-jump`). |
| `tap-shoot` | 240 | Step right, stop, tap shoot fourteen times, once every 0.1 s (`gun-cooldown`). |
| `turn-and-shoot` | 300 | Turn left, shoot walking and standing still, walk right (`body-flip`). |
| `wait-for-patrol` | 1100 | Stand still for nine seconds while the enemy on the upper ledge patrols (`enemy-ledge`). |
| `walk-left` | 360 | Walk left to the lower moving platform (the platform draw-order finding). |

