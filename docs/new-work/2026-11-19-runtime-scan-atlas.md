# Runtime scan: AtlasTexture regions apart from whole images, and never bound (#260, #666)

## What changed
#664 merged at 7fc318b, before this change reached its branch. The integrator noted on #664 that
Breakout's paddle draws AtlasTexture regions of one PNG (#666). The runtime scan counted any texture
with a `res://` path as an image. So an AtlasTexture saved as `.tres` would have been listed as an
image, and `init --runtime` could have bound it as the player's image. An embedded one was called
"made in code", which is wrong.

- `harness/godot/expectrail_scan.gd` sorts each texture into one of three lists:
  - `images`: whole image files, by extension (`.png`, `.webp`, `.svg`, `.jpg`, `.jpeg`, `.bmp`,
    `.tga`);
  - `atlasImages`: the files drawn as AtlasTexture regions;
  - `unsavedImages`: a count of everything else (embedded in a scene, made in code, or a resource
    file that is not an image).
- `expectrail.runtime-scan/v1` gets `atlasImages`. The schema, the example, the writer and the reader
  change together.
- `init --runtime` never takes a region as the player's image. It says so: "draws regions of
  res://… through an AtlasTexture; a binding names a whole image, so choose it by hand".
- Resolving the source image and frame region for review stays with #666. The saved-scene reader
  is unchanged.

## What was run
- A new Godot test draws four sprites under Crate Run's player: an AtlasTexture made in code, one
  saved as `.tres`, an ImageTexture made in code, and the whole `crate.svg`. Each is classified as
  above, and no image is guessed. With the scanner's atlas branch disabled, that test fails.
- `python3 -m unittest tests.test_runtime_scan`: 28 tests, OK, also with jsonschema blocked (CI's
  `capture-smoke` job has none).
- The full suite on the same change merged with main at 5731d67: 5,499 tests, OK, 42 skipped. On this
  branch, from main at 0642668: 5,499 tests, OK, 42 skipped.

## Not done
- Resolving an atlas region for review (source image and frame region): #666.

## Files
- `harness/godot/expectrail_scan.gd`, `expectrail/runtime_scan.py`
- `contracts/runtime-scan.v1.schema.json`, `contracts/examples/runtime-scan.v1.json`
- `tests/test_runtime_scan.py`, `docs/project-config.md`
