# Project config

A game can carry `expectrail.project.json` next to its project file (`project.godot` for Godot).
The format is `expectrail.project/v1`
([schema](../contracts/project.v1.schema.json),
[example](../contracts/examples/project.json)). `expectrail.project_config` reads it with the
standard library only. The verifier does not import jsonschema to do so.

The file names:

- the adapter (`godot` or `unity`) and, optionally, the toolchain;
- the entry scene, as a `res://` path to a file inside the project;
- the viewport, in pixels;
- `physicsTicksPerSecond` and `captureFps`;
- the input actions;
- one binding per object. A binding is a role (`player`, `coin`, …) mapped to exactly one of a
  node path or a group, plus the texture that object is drawn with (`res://`, a file in the
  project). Two roles may not name the same node or the same group.

### The viewport and the tick rate must be the game's own

The replay runs with what `project.godot` declares, so the config cannot change either value.
Before a configured Godot replay starts, and again on the copy with the change under test applied,
`expectrail.godot_project.require_declared_settings` compares:

- `viewport` with `display/window/size/viewport_width` and `viewport_height`: the game's logical
  viewport, in the game's own pixels. Godot's default, 1152 by 648, counts when they are unset.
- `physicsTicksPerSecond` with `physics/common/physics_ticks_per_second` (default 60).

If either differs, nothing runs, and the message names the field and both values. A value that is
present but is not a whole number in range, or a key set twice, is refused too; it is never replaced
by the default. Feature overrides such as `viewport_width.mobile` are not the setting the replay
uses and are not compared. `expectrail inspect` reads the same values with the same function.

A trace's own `viewport` is something else: the size of the window that was measured, in captured
pixels. Headless it is usually the logical viewport. With frames captured it can be larger, when
the game sets `display/window/size/window_width_override` and `window_height_override` (the bundled
game draws 800 by 480 into a 1600 by 960 window).

It does not name sizes. Configured Godot replays record every bound role's measured world and
screen boxes, engine visibility and stable instance identity in each row's `roleObjects`.
Drawing bounds take precedence over an explicitly labelled collision fallback. Groups are
resolved on every tick, including new instances. A missing or ambiguous binding refuses the
replay; a role never found is not a successful empty measurement.

Configured observations use these boxes, including the player's drawn bottom and each coin's
own size. They do not use the bundled `FEET_OFFSET` or coin-size constants. Older configured
traces without these measurements still load but cannot supply them. The unconfigured bundled
path retains its existing behaviour. See [role boxes](role-boxes.md) for supported geometry,
coordinate timing, visibility limits and the [tests](../tests/test_role_boxes.py).

A provider value, when present, is a `ref:` or `env:` name. An inline secret is refused.

Unknown fields are refused. A path that leaves the project (`..`, an absolute path, a backslash)
is refused, and a `res://` path must be a file that is there.

No file means the game has no config. The bundled game has none yet, and keeps the behaviour it
had: the harness finds `Player`, `Coin`, `Enemy` and `Bullet` by class or node name, the capture
rate stays 60, and its input actions and tick rate are still read from `project.godot`.

Its proposed config is [`harness/godot/platformer.project.json`](../harness/godot/platformer.project.json):
what `expectrail init` proposes for the game, without the `draft` flag and the draft route. It is
kept outside `game/platformer`, which only a person edits, until Sean decides whether it goes beside
`project.godot`. `python3 -m tools.bundled_config_parity` checks it on this machine: every field
must be what init reads from the game, each public route must replay to the same trace with and
without it (a config may only add the role boxes, the bindings and the measured window size), and
the Run it samples must reach the same decision with the same number of recorded vision answers,
which are looked up by each frame's exact bytes. Exit 0 means every case was the same, 1 that
something differs, 5 that it could not be run. The coins, enemies and bullets are not bound: they
have a class but no group, and a binding names a node or a group.

The replay does not compare a config's `viewport` or `physicsTicksPerSecond` with `project.godot`.
A wrong value is kept in the config, and no one is told. The parity check catches this for the
bundled config. A general check is [#657](https://github.com/Expectrail/Expectrail/issues/657).

A file that is present and not valid stops the run. The message names the field to fix. The route
reader, the gate and the harness all do this. None of them pretends the file was absent.

The harness does not receive a path to the file. Python reads it and passes the bindings as
`--bindings=<json>`. Inside the replay sandbox the game is a copy, and a path from the host would
not be there. The copy still contains the config file, because the whole project is what is copied.
The gate, when it has a base commit, reads this file from the base checkout and passes that capture
rate and those bindings to every replay; a head file that differs is not an accept.

## Inspect a game and draft the first route

From a shell with Expectrail installed, set `game` to the folder containing
`project.godot`. Inspect reads the starting scene and its nested text scenes.
It lists candidate player nodes, textures, input actions, cameras and ground
layers. It works without launching Godot. Add `--json` for the paths and settings, and `--runtime`
for what the running game builds in code (below).

```sh
game=./my-game
expectrail inspect "$game"
expectrail init "$game" --dry-run
expectrail init "$game"
```

Init writes a draft first route under `routes/`. When it finds one player and
one image, it also writes `expectrail.project.json` with `"draft": true`.
If a binding needs a choice, init writes `expectrail.project.draft.json`
instead. Open that review file, fill in the fields named by `unresolvedBindings`,
then save its `config` object alone as `expectrail.project.json`. For an
animated player, choose the representative image from the listed frame textures.
Use `--force` to replace an existing output config. Earlier routes are preserved.

### Choose the player: `--player NODE`

When the starting scene has several bodies and none is named `Player` (Breakout has `Paddle` and
`Ball`), name the one you mean:

```sh
expectrail inspect "$game" --player Paddle
expectrail init "$game" --player Paddle
```

Images are then suggested only from the sprites whose nearest physics body is that node. Each
suggestion (`imageSuggestions` in `--json`, the dry run and the review file) names the sprite, the
image file, the image's own size (read from a PNG header; other formats say "size not read") and,
when the sprite draws only part of the image through an `AtlasTexture`, each region as
`[x, y, width, height]`. Inspect follows a `SpriteFrames` and its `AtlasTexture`s saved inside the
scene to the image file. A region is offered as a candidate but never bound automatically: a
binding names a whole image, and the image's size is not the size drawn on screen, so a person
confirms it in the review page, which shows both. A `SpriteFrames` or `AtlasTexture` saved as its
own `.tres`, an atlas that is not an image file, a missing region, a region outside its image, or a
missing file is left unresolved, with what to supply. The review file keeps `selectedPlayer`, and the
review page reads the scene again for that node.

Review whether the route starts the game, moves the intended player and exercises
the behaviour you care about. The route command can test repeatability with three
replays. A person still chooses and approves the checks. Init measures no gameplay.

## Add what the game builds in code: `--runtime`

Saved scenes do not show what a script builds. A floor made in `_ready`, an image set in code or a
node added to a group at runtime is missing from the plain listing. `--runtime` also starts the game
headless on a copy, in the replay sandbox when the machine has one. The game runs 30 physics ticks
with no input. Then the listing adds the nodes the engine has at that moment: physics bodies and
areas, sprites with their image files, polygons, tile layers with their tile count and whether they
collide, cameras, and each node's groups and script class.

```sh
expectrail inspect "$game" --runtime
expectrail init "$game" --dry-run --runtime
```

On Crate Run (`tests/projects/crate-run`), the plain listing finds no ground layer. `--runtime` lists
`Floor`, a solid tile layer with 72 tiles that `main.gd` builds. It also says the crate is a filled
`Polygon2D` that draws no image file, so `bindings.player.texture` still needs a person's choice.

Init takes the player's image from the running game only when three things hold:

- the saved scenes named no image;
- there is one player candidate;
- exactly one whole image file is drawn under it, and nothing else: no texture made in code or
  embedded in a scene, and no AtlasTexture region. A region names part of an image, and a binding
  names a whole image, so it stays a person's choice (#666 covers resolving regions for review).

The dry run then says `"textureFrom": "runtime"`. In every other case the review draft lists the
reason, and nothing is guessed. A saved-scene finding is never replaced.

What the scan lists is the game's own report of itself, because the game's code ran in the same
process. It is setup information, never evidence for a verdict. With `--json`, `inspect` adds it under
`runtime`. The record that `expectrail.runtime_scan.scan` writes is `expectrail.runtime-scan/v1`
(`contracts/runtime-scan.v1.schema.json`). A scan that cannot be read is refused, never shown in part.

## See the bound objects at one tick

Once `expectrail.project.json` binds the objects, `--at-tick N` replays the game headless along the
config's first route (or `--route ROUTE`) and prints, for each bound object at physics tick N, its
node path, its box in captured-frame pixels, its box in world units and the engine's visible flag.
Add `--json` for an `expectrail.inspection/v1` record (`contracts/inspection.v1.schema.json`).

```sh
expectrail inspect "$game" --at-tick 60
expectrail inspect "$game" --at-tick 60 --route routes/walk.json --json
```

This is setup information, not a verdict and not pixel evidence: a box is the bounds of the
drawing (or, labelled, the collision shape), not its opaque pixels, and visible is the engine's
flag. A bound role with no object at that tick (not spawned yet, or removed) is listed as having
none, never given a box. A tick past the route, a missing config or route, and a binding the replay
never finds are refused with what to change.

## Verify the configured project in the app or CLI

`routes` lists route files or patterns inside the project. `approvedContracts` lists individual
check files; they may be in different subfolders. Naming a draft check does not approve it.
The app lists the usable routes and checks when you choose **Check folders**.

```sh
expectrail verify --project /path/to/after --base /path/to/before
```

The CLI and app share `expectrail.project_job`: they snapshot the games, select policy from the
base config, copy those policy bytes without editing them, and submit a normal verification
request. The changed config cannot replace the base's policy. Removing a selected check or
route from the changed copy is still a policy change. Draft configs retain the gate's
needs-review rule. Empty routes or checks never become an accept. This configured path currently
supports Godot; the older explicit `--head`, `--game`, `--routes`, `--specs` path is unchanged.
[App/CLI and draft-refusal tests](../tests/test_app_projects.py).

Vision normally uses the existing environment settings (`MODEL_API_KEY` and
`EXPECTRAIL_SAM_USD_CAP`). `providers.vision: "env:MODEL_API_KEY"` names that same setup;
no secret belongs in the config. To use an existing anchored recording, set both:

```json
"providers": {
  "vision": "ref:vision/vision-recording.json",
  "vision-calibration": "ref:vision/calibration.json"
}
```

Both are regular files inside the base project. They use the existing vision-recording and
vision-calibration contracts; the calibration must pass its validation. No model is constructed
as a fallback. A missing or invalid recording, or an exact image/question without an answer,
cannot clear the change. Unsupported vision references are refused with a fix. The worker log
names an unmatched image hash and prompt without printing a key. The optional request field
`project.visual` carries these references to the ordinary worker
([request schema](../contracts/verify-request.v1.schema.json),
[example](../contracts/examples/verify-request-recorded.json)).
