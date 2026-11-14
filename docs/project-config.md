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

It does not name sizes. A trace row's `body` is the player's own collision box for that tick.
`agents/observations.py` uses that box when the row has one, and the bundled constants only when
it does not. Coins stay on their constant until a row carries a box for them.

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
