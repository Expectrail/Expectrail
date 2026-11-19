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
- `python3 -m unittest tests.test_runtime_scan`: 27 tests, OK. Four of them start Godot 4.7.2
  headless, with the sandbox off because this machine has no bubblewrap:
  - Crate Run lists `Floor`, a solid tile layer with 72 cells, found only at runtime.
  - Crate Run with its config runs the configured scene.
  - The bundled game lists `Level/Player`, `res://player/robot.webp` and 21 nodes of class `Coin`.
  - A game that quits in `_ready` is refused with its exit code.
- By hand: `inspect --runtime` on copies of Crate Run and the bundled game took about 8.5 s each.
- Four mutations of the reader and of `merge` were each caught by the tests: an image taken despite
  an image made in code, the wrong owner body, the duplicate-path check removed, and runtime-only
  nodes not listed.
- The full suite on the branch merged with main at 73ac17f, with Godot installed:
  5,461 tests, OK, 41 skipped. An earlier run, at 048a871, had one failure: the schema-pattern test
  wanted a sample for the new image pattern. The pattern is now `^res://.+$` and has its sample.
- The sandboxed path was not run here, because this machine has no bubblewrap.
- CI's `capture-smoke` job on c02eb12 failed in the new step: `ModuleNotFoundError: No module named
  'jsonschema'`. An installed Expectrail has no dependencies, so the reader no longer uses
  jsonschema. It reads the schema with the gate's own reader (`expectrail.gate.record.errors`), and it
  checks each kind's fields and repeated values by hand. The 27 tests pass with jsonschema blocked.
  Full suite after the fix, merged with main at 73ac17f: 5,463 tests, OK, 41 skipped.

- After the integrator's note on #664 (Breakout's paddle draws AtlasTexture regions of one PNG,
  #666): the scan now lists whole image files (`images`, by file extension) apart from images drawn
  as AtlasTexture regions (`atlasImages`). A texture embedded in a scene, made in code or saved as a
  `.tres` is counted in `unsavedImages`. `init` never takes an atlas region as the player's image.
  A new Godot test draws four sprites under Crate Run's player: a code-made AtlasTexture, a saved
  `.tres` AtlasTexture, an ImageTexture made in code and the whole `crate.svg`. The test checks that
  each is classified as above and that no image is guessed. With the atlas branch of the scanner
  disabled, that test fails. `tests.test_runtime_scan`: 28 tests, OK, with jsonschema blocked as well.
  Full suite merged with main at 5731d67: 5,499 tests, OK, 42 skipped.

## Not done
- The Done-when run: `init --dry-run`, then a verification, on the second test project and on the
  bundled game. Crate Run's crate is a filled polygon, so its player image stays a person's choice.
- A game that needs input to leave a menu is scanned at its menu; `--runtime` presses nothing.
- Resolving an atlas region for review (source image and frame region): #666.
- `calibrate` stays with #330.

## Files
- `harness/godot/expectrail_scan.gd` (new)
- `expectrail/runtime_scan.py` (new)
- `contracts/runtime-scan.v1.schema.json`, `contracts/examples/runtime-scan.v1.json` (new)
- `expectrail/onboarding.py`, `expectrail/cli.py`
- `tests/test_runtime_scan.py` (new), `tests/test_package.py`
- `setup.py`, `.github/workflows/ci.yml`
- `docs/project-config.md`
