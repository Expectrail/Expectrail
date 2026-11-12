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
   any game node runs that tick ([how a press is sent](#how-a-press-is-sent)), and a second node
   records the player's position after every node has moved. It writes `trace.json` and quits when the route ends. Besides the player's position,
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

### What a game folder holds

Several records name a game by a digest of its files: `replay.json` (`game.tree`), the gate's record
(`headTree`, `baseTree`), the import cache's key and a verification job's inputs. Until November 12
each walked the folder its own way and the copy a replay runs was made a fifth way, so a file could be
replayed without being in the digest (#303). Now there is one walk, `harness/tree.py`, and the digests
and the copies are all made from it:

- Links are followed. What a link leads to is part of the game, under the link's own path, and is
  copied as a plain file: nothing in a replay's copy leads back out.
- A link may not leave the game folder, or the checkout when the caller gives one (the gate and the
  orchestrator do). A link that leaves, loops back into its own folder or leads nowhere, and anything
  that is not a file, a folder or a link (a pipe, a socket, a device), stops the replay before
  anything is copied or run. It is never followed and never left out quietly.
- `.godot` (the engine's cache, rebuilt from the game) and `.git` are not part of a Godot game, at
  any depth. Nothing else is skipped. Before this, a game at the root of its repository carried its
  `.git` folder into every replay's copy, sandbox included, and into its digest.
- An empty folder is not part of a game: no digest covered one, and now the copy holds none either.
- The copy returns the digest of the bytes it wrote, and that is what `replay.json` records. If the
  folder changed between the replay's first read (which keys the import cache) and its copy, the
  replay stops and runs nothing.
- The import cache is keyed by the same digest and imported from a copy of its own. A cache is
  stored only when that copy is the tree the key names; if the folder changed in between, nothing is
  stored and the run imports directly.

For a game with no links, no `.git` and no special files the digest is what it was: a test holds that
for the bundled Godot and Unity games against the old definition, and a real replay of `game/platformer` gave
the same `game.tree`, the same 120 frame hashes and the same trace as before the change.

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

## The ground under the player

Each row of the position log may carry `ground`: the world y of the highest solid tile surface under
the player's body. The surfaces are read from the tiles' own collision shapes, so they stay put when
a bug switches the level's collision off. Three columns are asked: under the middle of the body and
under its two ends, because a body rests on the highest point beneath it, on a slope or on a ledge
it has half walked off. A surface counts when it is no more than 64 px above the player's origin,
so a player sunk into the floor is still measured against the floor it sank into.

The ends are the player's own: the leftmost and rightmost points of its collision
(`CollisionShape2D` and `CollisionPolygon2D` children that are not disabled), measured where the
body is in the world, each pulled in by 1.25 px so that a wall the body touches is not counted as
under it. A scaled body, a scaled parent and a mirrored body are measured as they stand; a shape
off to one side gives two different ends, and the middle column is midway between them. A player
with no collision to measure is given 20 px either side of its origin. The bundled robot's shape is
42.5 px wide and centred, which is those same 20 px.

So the columns belong to the game being measured. A change that makes the player's collision
narrower or wider moves them, and can move the ground the harness logs. Measured on
`tests/routes/slope.json` with the robot's shape made 6 px wide and lifted 10 px (the merge guard's
run on #349): on the slope its feet are 17.2 to 32.8 px below the ground main's harness logged and
5.9 to 10.0 px below the ground logged now. The gate reads the logged ground. The fix loop's
verifier does not: it works the ground out again from the clean level with a fixed 20 px
(`surface_under` in `agents/observations.py`).

A row with nothing under the body has no `ground`, and a check against the ground cannot be decided
there: it is needs-review, never a guess (#346).

Until November 12, 2026 the edges were always the robot's 20 px. Godot's kinematic character demo
has a player 14 px wide: standing on the floor 20 px from a step it had a column inside the step,
the step's top was read as its ground, and the clean game was rejected (#348). The bundled game
logs the same ground in every row before and after, on its four routes and on a route up its slope.

Still the bundled robot's: the 64 px, and the 13.25 px from the origin to the feet that the check
itself uses (#259). The kinematic demo's feet are 7.2 px below its origin, so the check reads it
6 px lower than it stands. A platform that is a body and not a tile (one-way, moving) has no ground
line. A rotated capsule or circle is measured by the corners of its box, a little wider
than it is.

## How a press is sent

A route names actions. The harness sends each press and release as an input event, the way one
reaches a game from a player, and sends it on at once so it arrives in the tick the route names
(the engine otherwise holds events until the next drawn frame):

- **The action has a key or a pad button bound to it:** that key or button is pressed, the first one
  the project lists. Every way of reading input sees it: the action's state in a tick
  (`Input.is_action_pressed`), `_input`, `_unhandled_input`, `_unhandled_key_input`, and a button
  whose shortcut is the action. Any other action bound to the same key is pressed with it and
  released with it, as it is for the player. So a route that holds two actions sharing their first
  key over each other does not do what it says: releasing one lets go of the other, and nothing
  reports it yet. In the bundled game `jump`, `move_left` and `move_right` share their first key
  with the player-two actions, which only matter in split screen, where no route goes.
- **It has none** (nothing bound, or only a mouse button or a stick): an action event is sent. The
  action's state, `_input` and `_unhandled_input` see it. A button's shortcut does not: the engine
  offers only key and pad-button events to shortcuts.

Until November 12, 2026 the harness called `Input.action_press`, which sets the state and sends no
event. A game started from a menu, or one that reads a pause key in `_unhandled_input`, was replayed
without ever starting, and the replay said nothing. The bundled game polls, so its traces and frames
are the same before and after (four routes, compared byte for byte).

What a route still cannot say: a mouse click, a key that is no action, an amount on a stick. A route
that names an action the project does not have is not stopped; the press goes nowhere.

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


## Adapters

`harness/adapters.py` is the one boundary between Expectrail and the engine that replays a route.
Each adapter wraps a runner that already exists behind one signature:

```python
from harness import adapters
replay = adapters.get("godot").run(route, out, patches=[seed, candidate])
# run(route, out, patches=None, *, game=None, fps=None, capture_frames=True) -> replay document
```

A replay that fails raises `SystemExit`, as `harness.run.run` always has; the web adapter turns the
web harness's `WebHarnessError` into one. Besides `run`, an adapter records what other code used to
hard-code about its engine: the clean project, the folders the engine writes for itself (left out of
the tree digest and of the fixer's copies), where frames are, the log file, the files a fix may edit
by default, how a prompt names the project, which suffixes are text, the capture rate, the physics
rate, the trace format, a default route and the seeded bugs.

| Adapter | Runner | `engine.name` | Project | Ignored | Log | Capture |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `godot` | `harness/run.py` | `godot` | `game/platformer` | `.godot` | `godot.log` | 60 fps, 120 physics ticks a second |
| `web` | `harness/web/run.py` | `chromium` | `apps/checkout/site` | nothing | none | one frame after each step |
| `unity` | `harness/unity/run.py` | `unity` | `game/unity-platformer` | `Library`, `Temp`, `Logs`, `obj`, `UserSettings` | `unity.log` | 50 fps, 50 physics ticks a second |

The Godot adapter's tree digest is byte-identical to `harness.run.tree_digest` on the game.

What takes an adapter:

- `agents/fixer.py`, `agents/escalation.py`, `agents/assurance/proposal.py` and
  `agents/export_scan.py` take `adapter=` and default to `godot`.
- `agents/domain_verifier.py` is the shared verifier. It takes an adapter, the domain's specs, an
  engine-observations builder, a behaviour check, the public routes and the folder of private routes,
  and returns the decision and an `expectrail.verification/v0` document. The checkout page's verifier
  (`agents.web_fix.verify`) runs on it.
- `--adapter` on `harness.replay_check` and `harness.check_seeded` (default `godot`; both also run
  `--adapter web`), and on `agents.web_bench` and `agents.web_fix` (default `web`; they accept any
  adapter whose replays write the web trace).
- Not yet: `agents/verifier.py`, the Godot verifier, still calls `harness.run` itself, and so does
  everything built on it (`agents/loop.py`, `agents/heldout_bench.py`, `agents/matrix.py`,
  `agents/judge_bench.py`). An `--adapter` on those would switch some of their replays and not others.
  `harness/demo_clips.py` records the Godot demo's clips and reads the robot from the Godot trace.

A new engine is one module: build an `Adapter`, call `adapters.register(adapter)`, and give the shared
verifier its specs, its engine observations and its behaviour check. `tests/toy_domain.py` does that
for a stand-in engine, and `tests/test_domain_verifier.py` verifies fixes to it with nothing edited
elsewhere. The Unity adapter is registered beside the other two; its runner needs a player built
beforehand, which it takes from `$EXPECTRAIL_UNITY_PLAYER` (see Unity harness, below).

## Unity builds in CI

`.github/workflows/unity.yml` builds the Unity game, `game/unity-platformer` (Platformio on Unity
6000.3.21f1), with GameCI's `game-ci/unity-builder` v4.8.2, pinned by commit. The first build that
activated the licence was run 7 (42713673108, Nov 9, 2026); GameCI's login cannot answer a two-factor
prompt, so the Unity account the secrets belong to has two-factor sign-in off.

- **When it runs.** On `workflow_dispatch`, and on pull requests that touch `game/unity-platformer/`,
  `harness/unity/`, a `harness/routes/unity-*.json` route or the workflow itself. A change to
  `harness/run.py` or `harness/adapters.py`, which the Unity runner imports, does not start it. Every run waits for a person's approval (below), so it is
  kept off every other pull request.
- **The licence.** The build job runs in the `unity` GitHub Environment and reads `UNITY_LICENSE`
  (the contents of a Unity Personal `.ulf` file), `UNITY_EMAIL` and `UNITY_PASSWORD` from it; no
  other secret. Unity Personal is activated online by GameCI's v4 flow from those three; no other
  activation route is tried. With none of the three set, the job prints a notice, builds nothing and
  succeeds, and the replay job is skipped. With one or two set it fails.
- **Approving a run.** The build runs the pull request's own code in a process that holds the Unity
  password: the Editor runs a project's editor scripts while it builds. Approve a run only after
  reading what the pull request changes.
- **One Editor at a time.** Unity's terms allow one running Editor per seat, so the build job is in
  one concurrency group for the whole repository (`unity-editor-seat`). GitHub keeps one run waiting
  in a group; a third run cancels the one already waiting.
- **What it builds**, in this order: the clean game, with GameCI's own build method and no harness,
  to prove the build works; the clean game with the harness package, the player the replays use;
  and the clean game with the harness and the environment canary
  (`harness/unity/fixtures/canary-env.patch`). The harness and canary projects are laid out
  (`--prepare-build`) before any build touches the workspace, and each build starts from a copy of
  the clean build's `Library/`. No Unity seeded bug exists yet, and a candidate fix from the fixer
  is never built.
- **The canary** runs in the build job, like `capture-smoke`'s: the patched game prints
  `EXPECTRAIL_CANARY` and `EXPECTRAIL_HELDOUT_DIR` from `PlayerController.Awake`, and the job fails
  if either is not empty. Its player is never uploaded. Only the clean player and the clean harness
  player are uploaded.
- **The Library cache** is keyed on the hash of the game's `Assets/`, `Packages/` and
  `ProjectSettings/`, restored for the clean build, and saved only from it, on `main`.
- **The replay job** needs no licence. It runs in `ubuntu:noble-20261024.1` pinned by digest, with
  Xvfb and Mesa's llvmpipe (`LP_NATIVE_VECTOR_WIDTH=128`, `LP_NUM_THREADS=4`,
  `GALLIUM_OVERRIDE_CPU_CAPS=sse4.1`), downloads the harness player, records the CPU model and Mesa
  version, replays `harness/routes/unity-smoke.json` twice, and fails unless the two match in every
  frame's hash and in the trace's hash. It runs as two copies on separate runners from one build. It also reports
  the level it found, whether the ground line from the tile cells agrees with the collider paths, the
  settle, the hazards and the errors the game logged. Its apt packages, like every apt step in the workflow, come from Ubuntu's snapshot archive as it
  stood at `UBUNTU_SNAPSHOT` (the workflow's env), not the live archive, so every run installs the
  same versions; only `ca-certificates`, which the HTTPS snapshot needs, comes from the live archive
  first. The job records Mesa's version and the snapshot. It starts once the harness player is uploaded, so a
  failed canary does not hide the replays.
- **Cross-runner.** A third job compares the two copies with `python3 -m harness.unity.trace_diff`:
  each trace field's first differing tick, count and largest gap; the level; the settle; and the
  frames, every differing one measured pixel by pixel (with Ubuntu's `python3-pil`; the job fails
  rather than sample without it). It fails on any trace difference. A differing frame passes only
  if it is the frame of the tick a real-time fade starts on, when both copies saw the same fade
  starts, or if it is within tolerance: no channel more than 2 of 255 apart and at most 0.5% of its
  pixels different. The tolerance comes from run 15 (42746239419, an EPYC 9V74 and a Xeon 8573C):
  every frame differed, in 1,557 to 2,351 of 1,536,000 pixels (about 0.15%), by 1 or 2 of 255. Run 14
  (42738742696, attempt 2, an EPYC 9V74 and an EPYC 7763) passed: identical traces, 199 of 200
  frames identical, frame 113 (a fade's first tick) at most 8 of 255 apart in a channel. Separate
  runners need not be different CPUs; each copy records its own.
- **Times** (each build, cold or warm, and each replay) are published as notices.

The `unity` environment has to be set up once, by hand, before the first build: add the three
secrets to it, add required reviewers, and leave "Prevent self-review" off if the reviewer also
triggers the runs. Until then, GitHub creates the environment the first time the workflow runs,
with no protection rules and no secrets, and the build job skips.

## Unity harness

`harness/unity/` replays a route on the Unity game and writes what `harness/run.py` writes for
Godot: `frames/f%08d.png` from 0, `trace.json`, `replay.json`, and the player's log, `unity.log`.
It has run in CI since run 7 (above); the Python side is also tested with a stand-in player
(`tests/unity_fake_player.py`).

```sh
python3 -m harness.unity.run --prepare-build --out runs/unity/harness             # lay out a project
python3 -m harness.unity.run --build --unity /path/to/Unity --out runs/unity/harness  # an activated Editor
python3 -m harness.unity.run --route harness/routes/unity-smoke.json --out runs/unity-smoke \
  --player runs/unity/harness [--patch ...]
python3 -m harness.unity.run --out runs/unity-smoke --compare runs/unity-smoke-2  # frames and trace hash
EXPECTRAIL_UNITY_PLAYER=runs/unity/harness python3 -m harness.replay_check --adapter unity \
  --route harness/routes/unity-smoke.json --runs 10
```

- **Build.** A Unity game runs only as a built player, and building needs a licensed Editor (CI, or
  one a person has already activated; the harness never activates Unity). `--prepare-build` copies
  the game, applies the patches, adds the package (`com.expectrail.harness`) to the copy's
  `Packages/manifest.json` as a relative `file:` dependency, and writes a `link.xml` under the copy's
  `Assets/` (Unity reads `link.xml` only there, not in packages). The Editor then runs
  `Expectrail.Harness.Editor.HarnessBuild.Build`: Mono, minimal stripping, StandaloneLinux64, OpenGL
  Core, a 1600 x 960 window, the game's start scene first, and the `EXPECTRAIL_HARNESS` define without
  which the package's runtime assembly is not compiled; it fails if that assembly is not in the
  player. No scene or script is edited.
- **Which player.** `build.json` beside the player holds a key: the digest of the game tree, the
  patches in order, the package, the start scene and the Unity version. `run` refuses a player whose
  key differs from the run it is asked for.
- **Time.** The harness sets `Time.captureDeltaTime` to `Time.fixedDeltaTime`, so a rendered frame is
  one physics tick (50 a second here), and sets it again every frame (run 7: set once at startup it
  did not hold). The player counts the physics steps in every captured frame and the runner fails
  the run if any frame held zero or two.
- **Before tick 0.** `Time.captureDeltaTime` does not lock `Time.unscaledTime` (Unity's reference for
  it says so), and Platformio fades its screen and its level banner on `Time.unscaledDeltaTime`. So the
  harness waits for the banner to come and go and the screen to fade in, holding `Time.timeScale` at
  0 while a fade is part-way, so the fade takes no game time. `replay.json` records the ticks this
  took (`settle.ticks`) and the frames it held (`settle.frozenFrames`).
- **Holds during the route.** A fade during the route (after a death, at the level's exit) is held
  the same way, from the end of the tick it starts on. Unheld, the respawn after a death came at a
  tick set by the machine's speed (run 10, 42726139650: positions up to 1,934 px apart). Held frames
  give no tick, row or frame and apply no route input; a physics step in one fails the run. Each
  fade start is a `real-time-fade-during-route` hazard with its tick, and only that tick's frame can
  differ between machines (the fade's first step is real time).
- **Holds of a fixed length.** Every hold, before tick 0 and during the route, waits for its fade to
  rest and then pads to a whole number of 120 frames, so every machine reaches every tick on the
  same frame count. The same fade rests after 18 to 53 frames depending on the machine, and with
  holds that long the view drifted from a few ticks after a hold even with the camera still during it
  (run 13, 42734687182): something in Unity or Cinemachine counts frames. Padding frames draw an empty
  scene (each camera's `cullingMask` is 0; overlay UI still draws), so they cost less; frames while a
  fade is part-way are drawn in full, since cheaper ones would fit more of them into the fade's real
  second. What this changed on the smoke route: the death's fade-out and fade-in fall in one hold,
  so it has one fade start (tick 113) where it had two (113 and 114), and the settle takes 76 ticks
  where it took 77.
- **Input.** The harness removes every device the machine reports, adds a virtual keyboard and mouse
  (the game's control scheme needs both), ignores window focus, and queues each tick's key states
  before the tick's fixed update. The game's Player actions have no Hold or Tap interactions, so no
  input timing depends on real time.
- **Recording.** One trace row after LateUpdate on every tick, in world pixels (Unity units times
  128, y down): the player, `onFloor` (the game's own feet test), `facing`, the coins, enemies and
  projectiles, the camera (`view`), the ground line under the player from the tile cells, and
  `objects`. The header has `levelSurfaces` (the ground tilemap's collider paths) and `levelArt`
  (where its tiles are drawn, from cell and sprite bounds, not rendered pixels). Frames are read with
  `ScreenCapture.CaptureScreenshotAsTexture` at the end of every tick's frame.
- **Environment.** The player gets `harness/run.py`'s allowlisted environment, llvmpipe's settings
  (`RENDER_DEFAULTS` in `harness/unity/run.py`, the same as the replay job's), and an empty home of
  its own, so PlayerPrefs start empty. Any failure raises `SystemExit`.
- **Pixels across CPUs.** llvmpipe generates code for the CPU it runs on, and `LP_NATIVE_VECTOR_WIDTH=128`
  alone no longer keeps AVX and FMA out; run 12 (42730554068) drew different pixels from frame 0 on an
  AMD and an Intel runner. `GALLIUM_OVERRIDE_CPU_CAPS=sse4.1` gives every runner one instruction set.
  Different AMD models have drawn identical frames with it. An AMD and an Intel runner still differ,
  in about 0.15% of each frame's pixels by 1 or 2 of 255 (run 15, 42746239419); run 12 measured no
  pixels, so how much of the difference the pin removed is not known. The cross-runner job's
  tolerance covers this; the trace, which the specs read, was identical.

The checks in `agents/observations.py` and `agents/gameplay.py` read these fields, but their constants
(the robot's feet 13.25 px below its origin, its 60 px height, the coin's size, the drawn floor's
8 px offset) were measured on the Godot game. Platformio's player has its feet 128 px below its
origin (both its colliders end 1 unit below it), so the ground spec on a Unity trace would run but
would not see a player sunk by less than about 115 px (128 - 13.25) until those constants come from
the game.
