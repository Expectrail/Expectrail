# Ask SAM about the player only when a pixel check on the probe names it (#286)

## What changed
Until now the observer asked SAM about the player on every planned frame of every pixel replay, even
when every check on that probe was about the enemy or the bullet. Those images were reserved against
the change's cap and sent, and judged nothing.

- `pixel.asks_player(checks)`: the player is asked about on a probe only when a check there is about an
  object that is not one of many (today: the player). `pixel.images_per_frame(player, objects)` is the
  most one planned frame can take.
- `SamAnchorObserver(..., player=False)` sends no player image. Every planned frame's player row is
  `asked: false` with the reason `pixel.NOT_ASKED_PLAYER`. The frames are still checked against the
  replay's digests and size before any box is asked about. Asking about nothing is refused before
  anything is sent.
- `pixel.observe(..., player=False)` refuses an answer that says it asked about the player anyway.
- The in-process replay (`run.py`), the capture job (`objects.json` now carries `"player": false` when
  the player is not asked) and `pixel-ask` all reserve and send only what the probe's checks name. The
  reader of `objects.json` accepts `{objects}` (the player too, as before) and
  `{objects, player: false}`, and refuses anything else, including a file that asks about nothing.
- Cost: a probe whose checks name one many-object role now costs up to 3 images a planned frame, not 4.

One existing assertion changed: `tests.test_jit_pixel_named` `test_the_replay_asks_about_the_named_objects_its_checks_name_and_reserves_for_them`
reserved and counted a player image a frame for a probe with only an enemy check. It now reserves
`MAX_BOXES` a frame and counts two images a frame (the two enemies), which is the behaviour this change
makes.

## What was run
- `python3 -m unittest tests.test_jit_pixel_player tests.test_jit_pixel_named`: 40 tests, OK (16 new).
- Full suite on the branch (main 02e66bd plus this change), after
  `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`:
  `python3 -m unittest discover -s tests -t .`, 3,952 tests, OK, 40 skipped.
- Nothing was dispatched, no model or SAM call was made, nothing was spent.

## Not done
- No live SAM run on the enemy or the bullet; recording such answers waits on Sean's live pixel run.
- At `MAX_FRAMES` 30, a probe naming one many-object role still reserves up to
  30 x 3 x 9 x $0.0025 = $2.025, just over the $2 per-change cap: a first live run needs shorter
  probes or `--sam-first`.

## Files
- `expectrail/jit/pixel.py`, `expectrail/jit/sam_observer.py`, `expectrail/jit/pixel_jobs.py`,
  `expectrail/jit/run.py`
- `tests/test_jit_pixel_player.py` (new), `tests/test_jit_pixel_named.py`
- `docs/jit.md`, `docs/new-work/2026-11-15-pixel-player-when-named.md`
