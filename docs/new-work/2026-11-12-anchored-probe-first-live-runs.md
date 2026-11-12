# The anchored probe's first live runs, written down, and a player on the picture's edge (#330)

## What changed
- `docs/sam.md`: what the five live runs of the anchored probe showed. Sean started them on
  November 12: the two outside games with the point at the origin, and the bundled game with its
  eight seeded bugs three times (twice at the origin, once 14 game pixels higher).
- `agents/sam_anchor.py`: a player exactly on the picture's right or bottom edge is asked about at
  the last pixel inside. Dodge the Creeps holds its player at x = 480, the picture's width, and
  three of its 13 frames were skipped as "outside the picture".

## What was run
- The five runs are Sean's: 43304967915, 43305243223, 43306507436, 43308321074, 43310237299. 308
  images, $0.77 counted. I read the numbers from each run's notices and, for the bundled game, from
  `anchor.json` on the `sam-probe-results` branch, and looked at frames 0, 60 and 100 of the
  layering and sinking v2 contact sheets from the first bundled run.
- The counts of frames outside the clean range in `docs/sam.md` were computed from those two
  `anchor.json` files with a script, not read by eye.
- The second and first bundled runs compared: 95 of 95 answers the same.
- `python3 -m unittest tests.test_sam_anchor`: 34 tests, OK.
- `python3 -m unittest discover -s tests -t .` on Python 3.13, main at 3bc07d9: 2358 tests, OK, 26 skipped.
- Not run: the Dodge the Creeps probe after the edge fix. It needs a run with the key.

## Not done
- No rule and no verdict. The numbers say which rule to try: the box's size and its reach above
  and below the point inside the range a clean run sets, with confidence as a low floor at most.
  It has to be set on one clean route and held against another before it means anything.
- The point for a game is still chosen by hand (`lift`). The harness does not log the middle of the
  player's collision body.
- A point on each coin, which is what the missing-texture bug needs.

## Files
`docs/sam.md`, `agents/sam_anchor.py`, `tests/test_sam_anchor.py`
