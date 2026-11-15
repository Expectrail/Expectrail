# The harness logs every enemy's and bullet's box, and pixel-reach measures them (#286)

## What changed
A pixel check about the enemy or the bullet needs to know where each is drawn, the way the player's
`body` box says where the player is. Until now the harness logged only their positions.

- `harness/godot/expectrail_harness.gd`: every row now carries `enemyBoxes` and `projectileBoxes`:
  `[id, left, top, right, bottom]`, the world box of each tracked enemy's and projectile's own
  collision, measured as the player's body is (`_body_extent`), with the id it has in `enemies` and
  `projectiles`. One with no collision to measure is left out. The header says
  `capabilities.objectBoxes: true`.
- Trace contract: `contracts/trace.schema.json` gains the two row fields, a `trackedBox` definition and
  the capability. New example `contracts/examples/trace-godot.json`: three rows of a real Godot trace
  (the bundled game on `harness/routes/combat.json`), one with a bullet. The Unity example's note says
  where the Godot fields are.
- Reader: `agents/sam_anchor.py` `object_boxes(trace, frame_size, frames, role)` places every `enemy` or
  `bullet` box in a frame, widened and scaled as `anchors` does the player's. A box wholly off screen is
  counted, not listed. No object on screen is an answer, not a gap. A trace without `objectBoxes` is a
  gap on every frame: a box is never guessed from a position.
- `expectrail/repro/pixel_reach.py`: objects the engine logs boxes for and the menu does not offer yet
  are measured as **named objects** (default: `bullet` and `enemy`; `--named none` gives the old
  record). Each probe gets `byObject`, each defect gets `reachIfNamed`, and the record gets `named` and
  `totalsIfNamed`. `reach` and `totals` mean what they did. Schema, a new example
  (`contracts/examples/repro-pixel-reach-named.json`), writer and reader are in this pull request. The
  reader recomputes `reachIfNamed` and `totalsIfNamed`, and refuses a probe whose `byObject` does not
  name exactly the named objects.
- `bench/jit/public/pixel-reach.json` was made again with named objects. The bench page and
  `docs/jit.md` give the result.

## What was run
- `python3 -m expectrail.repro pixel-reach --out <scratch>/out --jobs 2` in this container (Godot
  4.7.2-stable from `harness/get_godot.sh`, Xvfb, llvmpipe), 18 min 22 s, no model:
  `{"defects": 2, "inside-a-box": 2, "outside-every-box": 0, "no-difference": 0, "error": 0}`.
  - The player's numbers match the record of the morning exactly, probe for probe (compared by script).
  - `enemy-walks-backwards`: inside the enemies' boxes on 230 of the 241 differing planned frames (all
    25 probes, at most 7,145 pixels in one box); inside the bullets' boxes on 17.
  - `bullet-behind-scenery`: inside the bullets' boxes on all 67 differing planned frames (all six
    probes that shoot, at most 2,401 pixels); inside the enemies' boxes on 17.
  - No planned frame is a gap for either object on either defect.
- `harness/routes/combat.json` replayed on the bundled game: 180 rows, 129 with a bullet. In every row
  the box ids are the position ids. Bullet boxes measure 16 x 16 (radius 8), enemy boxes 50 x 36.
- `python3 -m unittest tests.test_object_boxes tests.test_repro_pixel_reach`: 42 tests, OK. The engine
  tests in `tests.test_object_boxes` ran with the engine (Godot found).
- Full suite on the branch merged with current main: see the pull request.

Nothing was dispatched and nothing was spent: no model call, no SAM call.

## Not done
- `enemy` is not a bound role yet, and the menu does not offer `enemy` or `bullet` to `sam-3.1-anchor`.
  The observer is still pointed at the player's box only. That is the next slice: point it at a named
  object's boxes, with one image per box, reserved against the cap.
- A difference inside a box is necessary for a pixel check to fail, not enough. Whether SAM answers
  differently there is for a recorded or live run to say.
- The Unity harness does not write `enemyBoxes` or `projectileBoxes`. Its traces have no `objectBoxes`,
  so the reader treats every frame as a gap for those objects.

## Files
- `harness/godot/expectrail_harness.gd`
- `contracts/trace.schema.json`
- `contracts/examples/trace.json`
- `contracts/examples/trace-godot.json`
- `agents/sam_anchor.py`
- `expectrail/repro/pixel_reach.py`
- `expectrail/repro/__main__.py`
- `contracts/repro-pixel-reach.v1.schema.json`
- `contracts/examples/repro-pixel-reach-named.json`
- `bench/jit/public/pixel-reach.json`
- `bench/jit/public/README.md`
- `docs/jit.md`
- `tests/test_object_boxes.py`
- `tests/test_repro_pixel_reach.py`
- `docs/new-work/2026-11-15-object-boxes.md`
