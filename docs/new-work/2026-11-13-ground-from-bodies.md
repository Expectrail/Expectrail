# The ground under the player includes platforms that are bodies

## What changed

Part of #259 (the trace slice). The harness's `ground` came only from tile collision polygons, so in a
game whose platforms are physics bodies the player had no ground: 43 of 120 frames in Godot's
kinematic_character demo, which made it needs-review whatever was changed (#385).

- `harness/godot/expectrail_harness.gd`: `_ground_under` takes the highest surface under the player's
  body from the tiles and from the authored collision of the level's platforms, read in this tick so
  a moving platform counts where it is. Platforms are every `StaticBody2D`, `AnimatableBody2D` and
  `CharacterBody2D` except the player and anything under or above it, and nodes of the enemy and
  projectile classes; a `RigidBody2D` or an `Area2D` is never ground. Shapes that are disabled do not
  count, so a platform switched off reads as no ground (needs-review), never as a false reject. A
  shape is its bounding rectangle (exact for rectangles; the box round a circle or capsule).
- Each row with a ground says where it came from: `groundFrom` is `tile` or `body`. The header's
  capabilities say `groundSources`: whether the level has tiles, and how many bodies count.
- `contracts/trace.schema.json` and `contracts/examples/trace.json` carry both;
  `expectrail/repro/evidence.py` lists `groundFrom` among the row fields.

## What was run

All with Godot 4.7.2 in this session:

- `tests.test_ground_under`: 20 tests, OK. New `PlatformBodyTest`: a 64 by 16 body over the
  stepped-ground level's gap is the ground there, named `body`, for `StaticBody2D`, `CharacterBody2D`
  and `AnimatableBody2D`; the tiles stay the ground over the floor, named `tile`; a disabled shape, a
  frozen `RigidBody2D` and an `Area2D` give no ground and count as no body. The existing tests (the
  gap with nothing over it has no ground, the step, scaled and mirrored bodies) are unchanged and pass.
- The bundled game: `harness.run` on the smoke and traversal routes gives every row's ground from
  tiles (240 and 360 rows); `groundSources` counts 3 bodies (its static and moving platforms; the
  enemy is excluded by its class). `python3 -m expectrail.orchestrator sample`: accept, reject,
  accept, as expected.
- Full suite on this branch: 2874 tests OK, 27 skipped.

- **The first outside trial on the pull request found a wrong reject**
  ([run 43422746940](https://github.com/Expectrail/Expectrail/actions/runs/43422746940)): the clean
  kinematic_character demo was rejected, "player is 21.121px past the boundary (above 304.5)" from
  frame 80, and so was the harmless change. The engine's log shows the player falling past a one-way
  platform (top 304) beside it: its edge column crossed the platform, and with the 64 px window that
  tiles use, a platform 21 px above the player's origin counted as the ground under it. Fixed:
  a platform counts only at or below the player's feet, less 4 px (`PLATFORM_SINK`); tiles keep the
  64 px window. Two new engine tests: a platform 20 px above the feet is not ground; one 2 px below
  them is. `tests.test_ground_under`: 22 OK. Full suite: OK.

- The trial after the fix ([run 43428126877](https://github.com/Expectrail/Expectrail/actions/runs/43428126877)):
  kinematic-character as pinned needs-review, no violation in 115 frames judged (was 77), no ground
  in 5 (was 43); broken still reject (71.7 px past 304.5, frame 44); harmless the same as pinned.

## Not done

- A platform shape that is a circle or capsule is measured by its bounding box.
- Bodies added to the level after the first record are not counted (the search runs once).

## Files

- `harness/godot/expectrail_harness.gd`
- `contracts/trace.schema.json`, `contracts/examples/trace.json`, `expectrail/repro/evidence.py`
- `tests/test_ground_under.py`
- `docs/new-work/2026-11-13-ground-from-bodies.md`
