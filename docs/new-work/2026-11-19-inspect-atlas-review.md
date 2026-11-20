# Inspect resolves a selected player's atlas frames for review (#666)

## What changed
The saved-scene reader now follows a `SpriteFrames` and its `AtlasTexture`s saved inside a scene to the
image file. It keeps the source image and each frame region apart. Before this, Breakout's paddle gave
"the saved frame collection cannot be read", because its frames are `SubResource` references.

- `expectrail inspect` and `expectrail init` take `--player NODE`, the body the developer selects.
  Image suggestions then come only from sprites whose nearest physics body is that node. A node that
  is not a body in the starting scene is refused, and the bodies are listed.
- The report gets `imageSuggestions` whenever there is one player: the sprite, the property, the image,
  the image's own size from its PNG header (`null` for other formats), and the regions
  (`[x, y, width, height]`, or `null` when the image is drawn whole). With `--player`, it also gets
  `selectedPlayer`. Init's dry run and review file carry both.
- A region is offered as a candidate but never bound automatically. A binding names a whole image,
  so a person confirms it. This is the same rule #668 sets for the runtime scan.
- An atlas that is not an image file, an atlas with no region, a region outside its image, an
  external `.tres` `SpriteFrames`, an unknown sub-resource and a missing file are each left
  unresolved, with what to supply.
- The offline binding review page (`expectrail onboard`) reads the scene again for `selectedPlayer`.
  Under each candidate image it says how the sprite draws it: "draws regions 47 × 18 at (0, 0),
  47 × 18 at (47, 0) of this 94 × 18 image", or "draws this 4 × 4 image whole".
- `--player` with `inspect --at-tick` is refused.
- The shared interface for #652 is `onboarding.inspect(root, player=...)`. `expectrail/app.py` is not
  changed here.

## What was run
- `python3 -m unittest tests.test_inspect_atlas`: 11 tests, OK. The project is built to Breakout's scene
  shape: `Paddle` (a nested scene) draws two 47 × 18 regions of a 94 × 18 PNG, and `Ball` draws a whole
  4 × 4 PNG. Selecting Paddle offers only the strip and binds nothing. Selecting Ball binds its own PNG.
  The game files' SHA-256 values are the same before and after `inspect` and `init --dry-run`.
- Four mutations were each caught: regions not reported, sprite ownership ignored, the bounds check
  removed, and atlas resolution removed.
- `tests.test_init_inspect`, `tests.test_onboard`, `tests.test_onboard_review` and
  `tests.test_runtime_scan`: OK.
- I looked at the review page in Chromium at 1280 and 390 pixels wide. The region line sits under the
  strip's preview. Neither width scrolls sideways.
- Full suite on this branch from main at c7ce110: 5,425 tests, OK, 70 skipped.

## Not done
- Pinned Breakout itself was not run. Only this repository may be fetched from the session that built
  this. The Done-when run on Breakout (Paddle → 47 × 18 within 94 × 18; Ball → 4 × 4) is for a session
  that may fetch it.
- The local app (#370, #652) does not call the new argument yet. That is the app owner's file.
- `Sprite2D` with `region_enabled` or `hframes`/`vframes` is unchanged: it is still bound as a whole image.
- `SpriteFrames` and `AtlasTexture` saved as their own `.tres` are not followed.
- Sizes are read from PNG headers only.

## Files
- `expectrail/onboarding.py`
- `expectrail/onboard.py`
- `tests/test_inspect_atlas.py`
- `docs/project-config.md`
- `docs/new-work/2026-11-19-inspect-atlas-review.md`
