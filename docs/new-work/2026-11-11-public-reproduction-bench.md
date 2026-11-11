# A public reproduction bench of 24 defects, and what each changes in the engine's record (#285)

## What changed
Issue #285 measures reproduction: of the reported bugs in a bench, the share for which a generated
check fails on the bug build 3 times of 3 and passes on the clean game 3 times of 3. This is its
first slice, the bench itself, and one measurement that needs no model.

- `bench/jit/public/defects.json` (`expectrail.repro-bench/v1`, schema and example) lists 24 public
  defects of the bundled game, each a patch against the clean game and a bug report in a player's
  words: the 4 reported bugs, marked `tunedOn` because the trace signals were built around them, and
  20 written for the bench across nine of the ten defect families of #282 (none in missing or wrong
  assets). The game folder is not edited; every defect is a patch.
- `python3 -m expectrail.repro check` reads the bench strictly (no path outside `bench/` and
  `bugs/`; none with a part that names held-out material, in any case; none reached through a
  link, a linked folder on the way included; no id or patch twice; no empty report) and checks that every patch applies to a copy of the game.
- `python3 -m expectrail.repro visibility` replays every library probe on the clean game twice and on
  each defect build once and sorts each defect by what changed in the engine's record: a signal
  moved, the record differs and no signal does, or nothing differs
  (`expectrail.repro-visibility/v1`, schema; the reader recomputes the labels and totals from the
  rows and refuses a record that disagrees with itself). `render` prints the record as the table on
  the bench's page, and a test holds the page to the record and the record to the bench.
- Four first-draft defects were replaced after replays showed they changed nothing or could not be
  reached: two camera defects edited `level/level.gd`, which the level scene does not load.

## What was run
- After the merge guard's first review of #306 (a linked folder on the way was followed, so a bench
  file could reach a held-out folder through one; the name rule was case-sensitive and missed
  `blind` and `heldout`): the reader now resolves a path once and requires it to be exactly its own
  path, and one rule for held-out names is applied to the text and to the resolved path. The
  guard's cases are tests in `Refusals`. A record that names a signal the trace does not have is
  refused as well.
- `python3 -m expectrail.repro visibility --out <dir> --jobs 2`, in a cloud container with the pinned
  Godot 4.7.2, on November 11, not in CI, no model: a signal moves for 17 of 24 (for `coin-stays`
  only by 0.01 px, a side effect), the record differs with no signal for 2 (both camera defects),
  nothing differs for 5. No field differed between the two clean replays and no replay was made
  again. The record is `bench/jit/public/visibility.json`. An earlier full run of the same command,
  before the four replacements, gave the same row for each of the 20 defects the two runs share.
- By hand, once per build, not kept as tests: `no-shooting-in-air` fires 0 bullets against the clean
  game's 1 on a route that jumps and shoots at once; with frames captured on a route that walks
  right and fires three times, `enemy-walks-backwards` differs from the clean game on 130 of 130
  frames and `bullet-behind-scenery` on 100 of 130, and two clean captures were identical.
- `python3 -m expectrail.repro check`: 24 defects, 24 apply.
- `python3 -m tools.merge_guard --base origin/main --head HEAD`: nothing to report.
- The full suite, `python3 -m unittest discover -s tests -t .`, on the branch merged with main: the
  result is in the pull request.

## Not done
- No live generation was run on this bench, so there is no reproduction rate and no breakdown of
  misses. That takes a dispatch from main that calls a paid model; a person starts it.
- The visibility measurement was not run in CI.
- `coin-counts-twice` and `coin-counter-stuck` need the pause menu, which no route can open: no run
  has shown them change anything.
- The visibility measurement replays the library probes only, not probes a model might propose.
- Not built: the scorer that reads a live run's records, the miss vocabulary, a bench mode in the
  workflow, and steps 3 to 6 of the issue.

## Files
`expectrail/repro/__init__.py`, `expectrail/repro/__main__.py`, `expectrail/repro/bench.py`,
`expectrail/repro/visibility.py`, `contracts/repro-bench.v1.schema.json`,
`contracts/repro-visibility.v1.schema.json`, `contracts/examples/repro-bench.json`,
`bench/jit/public/` (`defects.json`, `visibility.json`, `README.md`, 20 defect folders),
`bench/jit/README.md`, `docs/jit.md`, `docs/contracts.md`, `tests/test_repro_bench.py`
