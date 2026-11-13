# A route can open the pause menu: the harness keeps running while the game is paused, and menu probes (#285)

## What changed
- `harness/godot/expectrail_harness.gd`: on a harness run, the harness sets its own process mode to
  "always". It is an autoload and inherited the root's mode, so a game that paused its tree paused
  the harness too: no further press was sent, no row recorded, and the route never reached its last
  tick. Runs of a game that never pauses are not affected; nothing else in the harness changed.
- `tests/projects/pause-input/`: a small Godot project for the test (a marker that walks while
  `right` is held; a key pauses and unpauses the tree from a root that always runs).
  `tests/test_pause_input.py` replays it drawn and headless and holds the position at each tick.
  `.github/workflows/ci.yml`: one step in `capture-smoke` runs it with `EXPECTRAIL_ENGINE_TESTS=required`.
  No secret, permission or environment changed.
- `expectrail/repro/menu.py`: menu probes, each library walk (`hold-right`, `hold-left`, `reverse`)
  then one tap of a menu action and 90 ticks with the menu drawn. The action is named by the caller
  and refused unless the game's `project.godot` declares it, or if it is already in the catalog.
  It is not added to the mechanics profile. No offer of the generator reads this module (a test holds it).
- `python3 -m expectrail.repro menu --menu-action <name>` prints them; `evidence` takes
  `--menu-action` (repeatable) and `--menu-only`.
- `bench/jit/public/menu-evidence-coin-counter-stuck.json` and `menu-evidence-coin-counts-twice.json`
  (`expectrail.repro-evidence/v1`, no new contract), shown on the bench's page with what they say;
  a paragraph in `docs/jit.md`.

## What was run
- Before the harness change, the pause test project's 70-tick route, headless, on Godot 4.7.2: no
  trace after 120 s (killed). The bundled game with a route that walks right and presses
  `toggle_pause`: 4,439 frames in 10 minutes for a 400-tick route (killed). One captured frame shows
  the pause menu with the counter at 5.
- After: `python3 -m unittest tests.test_pause_input tests.test_event_input` under a virtual display
  with Godot 4.7.2: 14 tests, OK.
- `python3 -m expectrail.repro evidence --defect coin-counter-stuck --menu-action toggle_pause
  --menu-only --jobs 3` and the same for `coin-counts-twice` (Godot 4.7.2, llvmpipe, a cloud
  container, no model, not in CI; about 3 min 20 s each): for both, `hold-right-then-toggle-pause` and
  `reverse-then-toggle-pause` are screen-only, 77 of 232 frames from frame 155 (tick 310, the menu's
  tap), the difference in the top-left corner; `hold-left-then-toggle-pause` shows nothing; two
  clean replays identical; no engine retries.
- `python3 -m unittest tests.test_repro_menu`: 25 tests, OK.
- The full suite on the branch merged with main: see the pull request.

## Not done
- No offer gives menu probes to the generator: a check about the counter would have to speak about
  the screen, which is #286. No live run was made or dispatched; nothing was spent.
- The menu action comes from the command line. Its place is the project config of #259.
- The hand findings of the baseline (`route-never-reaches` for the two defects) are left as written:
  they describe the baseline run.
- The other library probes (jumps, shooting) were not given a menu variant.

## Files
- `harness/godot/expectrail_harness.gd`
- `tests/projects/pause-input/` (README, `project/`, `routes/pause.json`), `tests/test_pause_input.py`
- `.github/workflows/ci.yml`
- `expectrail/repro/menu.py`, `expectrail/repro/__main__.py`, `tests/test_repro_menu.py`
- `bench/jit/public/menu-evidence-coin-counter-stuck.json`, `bench/jit/public/menu-evidence-coin-counts-twice.json`,
  `bench/jit/public/README.md`
- `docs/jit.md`, `docs/new-work/2026-11-13-pause-menu-route.md`
