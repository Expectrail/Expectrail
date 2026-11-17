# A SAM stand-in for the bullet drawn behind the scenery, captured on the real engine (#286)

## What changed
`bullet-behind-scenery` is the bench's other screen-only defect. The no-model sensor cannot be asked about the
bullet (its bank holds no bullet template), so SAM is the only observer that can judge a check about it. This
change prepares that check offline, the way #598 did for the enemy's facing.

- `tools/bullet_visible_stand_in.py` writes a hand-written stand-in proposal of three `visible` bullet checks
  for `sam-3.1-anchor`, with the candidate withheld, under `signals-reach-evidence-pixel`:
  - `shoot-left-every12` from frame 50;
  - `move-fire-left` from frame 90;
  - `move-fire-right` from frame 10 to 80.
  It goes through the parser a model's answer goes through, and `model: hand-written-stand-in`, so the
  reproduction score gives a record made from it no result.
- The tool refuses a window that would leave a check that can never be kept, read from a measured capture
  plan (`--measure CAPTURE` writes `capture-plan.json`):
  - a planned frame with more than `pixel.MAX_BOXES` (3) bullets on screen, which SAM is not asked about
    (`move-fire-left` has 4 on frame 80 on every replay);
  - a frame the engine's record cannot place the bullets in;
  - no frame in the window with a bullet on screen on every clean replay;
  - a planned frame the bench's evidence lists a bullet partly on screen (`edges`).
- `bench/jit/stand-in/bullet-behind-scenery-visible/` holds the proposal, the capture plan, the capture run's
  record and a page saying what it shows.
- `docs/jit.md` has a paragraph on it, and `expectrail/repro/score.py`'s docstring names this stand-in.
- `.gitignore` lets the new tool in, as it does `tools/faces_motion_stand_in.py`.
- Found on the way, opened as #605: SAM is asked about every planned frame of a probe whatever the checks'
  windows, so the windows do not lower the reservation.

## What was run
- On the real engine here (Godot 4.7.2-stable from `harness/get_godot.sh`, Xvfb; no model, no SAM, no key in
  the environment, not in CI):
  - `jit run --proposal ... --observer sam-3.1-anchor --pixel-capture` on the stand-in with whole-probe windows:
    10 min 49 s, 27 replays, status `complete`. `--measure` on it wrote `capture-plan.json`.
  - The same with the committed windows, at `--budget-usd 2`: 10 min 33 s, 27 replays, `complete`, spend
    $0.2089 at assumed prices, 0 SAM images. `--measure` on it gave the same plan. Its record is committed.
  - `pixel-budget --budget-usd 2` on that record: `1.7911`.
  - `pixel-ask --budget-usd 1.7911` on the capture: exit 1, `{"asked": false, "reason": "the 27 replays need up
    to 1296 images, $3.2400, over the budget of $1.79; nothing was asked"}`.
  - Inside the bullets' prompt boxes on the planned frames, most pixels differ between the clean game and the
    bug build. Frame 60 of `move-fire-left`, looked at by hand: the clean game draws the bullets at the wall,
    the bug build draws none there.
- `python3 -m unittest tests.test_bullet_visible_stand_in`: 25 tests, OK. They run no game and call no model.
- Full suite on the branch (main 791f50b plus the change): see the pull request.

Nothing was dispatched and nothing was spent.

## Not done
- SAM has not been asked about a bullet. Whether it finds a bullet drawn behind the scenery is untested. The
  asking step needs SAM's key and a budget of at least $3.24 for these three checks; with jit.yml's $2 cap,
  one check on one probe.
- No model has proposed a bullet check.
- #605: plan only the frames inside the checks' windows.

## Files
- `tools/bullet_visible_stand_in.py` (new)
- `tests/test_bullet_visible_stand_in.py` (new)
- `bench/jit/stand-in/bullet-behind-scenery-visible/` (`README.md`, `jit-proposal.json`, `capture-plan.json`,
  `jit-run.json`; new)
- `docs/jit.md`
- `expectrail/repro/score.py` (docstring only)
- `.gitignore`
