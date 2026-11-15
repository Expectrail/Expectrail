# Measure whether a pixel check, as offered today, can see the screen-only defects at all (#286)

## What changed
A pixel check is judged from what `sam-3.1-anchor` says inside one box a frame: the logged body box of
an object the proposer's menu offers, widened by 4 game pixels, on the frames the observer plans. The
menu offers one object, the player. Before Sean pays for the first live pixel run, this measures with no
model whether the pixels that box shows ever change on the bench's screen-only defects.

- `expectrail/repro/pixel_reach.py`: each library probe is replayed with frames on the clean game once
  and on each named defect build once (default: the screen record's screen-only defects). On every
  planned frame, the pixels inside the box are compared, using the observer's own frame plan
  (`SamAnchorObserver.frames`) and box (`agents/sam_anchor.anchors`, body box, default pad), on each
  build's own position log. Each defect is `inside-a-box`, `outside-every-box`, `no-difference` or
  `error`. An object the menu offers that has no logged box stops the measurement instead of being
  skipped.
- New record `expectrail.repro-pixel-reach/v1`: schema, example, writer and reader in this pull
  request. The reader recomputes each defect's reach from its probes and the totals from the rows.
- `python3 -m expectrail.repro pixel-reach` and `pixel-reach-render`.
- The measured record is committed as `bench/jit/public/pixel-reach.json`, with a section on the bench's
  page and a paragraph in `docs/jit.md`.

## What was run
- `python3 -m expectrail.repro pixel-reach --out runs/repro-pixel-reach --jobs 2` in this container
  (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb, llvmpipe), 17 minutes 49 seconds, no model:
  `{"defects": 2, "inside-a-box": 2, "outside-every-box": 0, "no-difference": 0, "error": 0}`.
  - `enemy-walks-backwards`: planned frames differ on 25 of 25 probes, inside the player's box on 9
    frames of `hold-right` (at most 1,125 pixels); 232 of the 241 differing planned frames differ only
    outside it.
  - `bullet-behind-scenery`: planned frames differ on the 6 probes that shoot, inside the box on 17 of
    67 (at most 6,610 pixels).
- Two of those probes replayed again by hand and cropped around the box (`move-fire-left` frames 50 and
  60, `hold-right` frames 90 and 100), looked at, not kept: what differs inside the player's box is the
  bullets (drawn over the player on the clean game, behind it on the defect build) and an enemy facing
  the other way. The player is drawn the same.
- `python3 -m unittest tests.test_repro_pixel_reach`: 16 tests, OK. `tests.test_repro_screen` and
  `tests.test_repro_bench`: 85 tests, OK.
- Full suite on the branch merged with current main: see the pull request.

Nothing was dispatched and nothing was spent: no model call, no SAM call.

## Not done
- Whether SAM's box of the player changes when a bullet or an enemy overlaps it is not measured; only a
  recorded or live SAM answer on these frames can say.
- The coin-counter defects are not measured (pause menu only, and the counter is text, which
  `sam-3.1-anchor` cannot tell).
- Pixel checks still cannot name the enemy or the bullet: the harness logs their positions, not their
  boxes, and the SAM observer is pointed at the player only.

## Files
- `expectrail/repro/pixel_reach.py`
- `expectrail/repro/__main__.py`
- `contracts/repro-pixel-reach.v1.schema.json`
- `contracts/examples/repro-pixel-reach.json`
- `bench/jit/public/pixel-reach.json`
- `bench/jit/public/README.md`
- `docs/jit.md`
- `tests/test_repro_pixel_reach.py`
- `docs/new-work/2026-11-15-pixel-reach.md`
