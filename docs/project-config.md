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
layers. It works without launching Godot. Add `--json` for the paths and settings.

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

Review whether the route starts the game, moves the intended player and exercises
the behaviour you care about. The route command can test repeatability with three
replays. A person still chooses and approves the checks. Init measures no gameplay.

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
