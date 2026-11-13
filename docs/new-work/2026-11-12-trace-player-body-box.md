# The position log carries the player's own box (#259, for #327 and #330)

## What changed
Sean chose on November 12 how the anchored box check ends when a frame differs (needs-review until
blind test 4; #327). Its first piece either way is that the box is the game's own and not a number
somebody typed.

- **The trace contract gains `body`** (`contracts/trace.schema.json`, its example): per row, the
  world box `[left, top, right, bottom]` of the player's own collision in that tick. Optional: a
  player with no collision to measure has none, and older traces have none.
- **The writer:** `harness/godot/expectrail_harness.gd`. `_body_extent` measures the collision
  shapes and polygons that are not disabled, where the body stands in the world, on both axes.
  `_body_span` (the ground's columns, #349) now takes its two ends from it, so there is one
  measurement and not two.
- **A reader:** `agents/sam_anchor.py --box body [--pad N]` asks the visual observer with that
  box widened by 4 game px each way, its middle as the point. A tick with no `body` is not asked
  about. The report says `"box": "body"` and its pad, and `agents/anchor_rule.py` refuses to
  compare it with answers to a typed box or to another pad.
- `.github/workflows/sam-probe.yml`: the `box` input also takes `body`. `.github/workflows/ci.yml`:
  one step in `capture-smoke` runs the new engine tests with a skip counted as a failure. No
  secret, environment or permission is added to either.
- `docs/harness.md` ("The player's own box") and `docs/sam.md`.

## What was run (Godot 4.7.2)
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_body_box`: 8 tests, OK. The test
  level's 24 by 16 shape is logged as (-12, -8, 12, 8) around its origin; at scale 2 as
  (-24, -16, 24, 16); 10 px to one side as (-2, -8, 22, 8), and mirrored as (-22, -8, 2, 8); a
  polygon the same as the shape; a disabled shape gives no `body` in any row. The bundled robot is
  (-21.25, -41.25, 21.25, 13.25) in all 240 rows of the smoke route, and its bottom is the 13.25
  the ground check has as a constant.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_ground_under`: 14 tests, OK
  (the ground's columns come from the same measurement now).
- The bundled game on `smoke`, `coins`, `combat`, `traversal` and `tests/routes/slope.json`, main's
  harness against this one: every row is the same but for the new field (240, 240, 180, 360 and
  420 rows, `body` in every one), and every frame's sha256 is the same (120, 120, 90, 180, 210).
- The traversal route replayed with this harness and the probe's `--box body --dry-run`: frame 0 is
  asked with the box 749,663 to 851,788 in the frame. Drawn with a stand-in answer, the box frames
  the robot on frames 0 and 100 (looked at).
- `python3 -m unittest tests.test_anchor_rule tests.test_sam_anchor`: 104 tests, OK.
- Every shell step of the probe job passes `bash -n`; both workflows parse.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, main at dddced6: 2581 tests, OK, 27 skipped.

## Not done
- **Nothing has been asked of the service with the body's own box.** For the robot it is 50.5 by
  62.5 game px around a point 14 px above the origin; the typed box of the recorded runs was 48 by
  68 around a point 17 px above. A different question, so the recorded answers do not carry over.
  One run for Sean (131 images, $0.33): probe mode, `anchor` ticked, `box` body, `clean_routes`
  coins,combat,traversal. It has to show what the typed box showed.
- Only the player has a box. Coins, enemies and bullets are still logged as points (#259).
- The ground check still takes the feet from its constant and not from `body` (#259). The
  kinematic demo's 6 px error stays until it does.
- The check itself in the gate, ending in needs-review on a difference (#327), is the next piece.
- The outside projects were not run here. The trial runs on this pull request because the harness
  changed; its verdicts should not move (the new field is read by nothing in the gate).

## Files
`contracts/trace.schema.json`, `contracts/examples/trace.json`,
`harness/godot/expectrail_harness.gd`, `agents/sam_anchor.py`, `agents/anchor_rule.py`,
`tests/test_body_box.py`, `tests/test_sam_anchor.py`, `tests/test_anchor_rule.py`,
`.github/workflows/ci.yml`, `.github/workflows/sam-probe.yml`, `docs/harness.md`, `docs/sam.md`
