# `init --runtime` and `inspect --runtime`: what the running game builds in code (#260)

## What changed
`expectrail init` and `expectrail inspect` read saved scenes and never start the game. So they miss
whatever a script builds. On Crate Run, the plain listing finds no ground layer, because `main.gd`
builds the floor in `_ready`.

`--runtime` also starts the game headless on a copy, in the replay sandbox when the machine has one.
The game runs 30 physics ticks with no input. Then the listing adds the nodes the engine has at that
moment.

- `harness/godot/expectrail_scan.gd` is a new autoload, added to the copy only, never to the game.
  It lists physics bodies and areas, sprites with their image files, polygons, tile layers with their
  tile count and whether they collide, and cameras. For each node it gives the groups and the script
  class.
- `expectrail/runtime_scan.py` holds the writer (`scan`), the reader (`problems`) and `merge`, which
  adds a scan to the saved-scene listing.
  - The game's file is read as untrusted data. Duplicate keys, unknown fields, an image outside
    `res://`, a path outside the scene, a duplicate path and an oversized file are each refused with
    "cannot tell".
- `expectrail.runtime-scan/v1`: the schema, an example made from a real Crate Run scan, the writer and
  the reader.
- `init` takes the player's image from the running game only when three things hold: the saved
  scenes named none, there is one player candidate, and exactly one image file is drawn under it with
  none made in code. The dry run then says `"textureFrom": "runtime"`. In every other case the reason
  is listed (for Crate Run: "Player/Body: Polygon2D draws no image file (a filled polygon)"). A
  saved-scene finding is never replaced.
- `--runtime` together with `--at-tick` is refused before anything runs.
- CI runs `tests.test_runtime_scan` with `EXPECTRAIL_ENGINE_TESTS=required`, so its Godot tests
  cannot skip there. The module and the script are in the wheel.

## What was run
- `python3 -m unittest tests.test_runtime_scan`: 25 tests, OK. Four of them start Godot 4.7.2
  headless, with the sandbox off because this machine has no bubblewrap:
  - Crate Run lists `Floor`, a solid tile layer with 72 cells, found only at runtime.
  - Crate Run with its config runs the configured scene.
  - The bundled game lists `Level/Player`, `res://player/robot.webp` and 21 nodes of class `Coin`.
  - A game that quits in `_ready` is refused with its exit code.
- By hand: `inspect --runtime` on copies of Crate Run and the bundled game took about 8.5 s each.
- Four mutations of the reader and of `merge` were each caught by the tests: an image taken despite
  an image made in code, the wrong owner body, the duplicate-path check removed, and runtime-only
  nodes not listed.
- The full suite on the branch merged with main at 048a871: see the pull request.
- The sandboxed path was not run here, because this machine has no bubblewrap.

## Not done
- The Done-when run: `init --dry-run`, then a verification, on the second test project and on the
  bundled game. Crate Run's crate is a filled polygon, so its player image stays a person's choice.
- A game that needs input to leave a menu is scanned at its menu; `--runtime` presses nothing.
- `calibrate` stays with #330.

## Files
- `harness/godot/expectrail_scan.gd` (new)
- `expectrail/runtime_scan.py` (new)
- `contracts/runtime-scan.v1.schema.json`, `contracts/examples/runtime-scan.v1.json` (new)
- `expectrail/onboarding.py`, `expectrail/cli.py`
- `tests/test_runtime_scan.py` (new), `tests/test_package.py`
- `setup.py`, `.github/workflows/ci.yml`
- `docs/project-config.md`
