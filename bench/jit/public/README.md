# The public reproduction bench

Issue #285 asks for one number: of the reported bugs in a bench, the share for which a generated check
fails on the buggy build 3 times of 3 and passes on the clean game 3 times of 3. This folder is the
bench that number will be measured on. Everything in it is public, and reproduction is developed on
it and on nothing else: never on a blind set, its logs or its counts.

**No reproduction rate has been measured.** That takes a live run from main, which calls a paid
model, and none has been made on this bench. What is here is the bench, one measurement that
needs no model (what each defect changes in the engine's record), and the scorer that will read a
live run's records when there is one.

## What is in it

[`defects.json`](defects.json) (`expectrail.repro-bench/v1`) lists 24 defects of the bundled
platformer. Each is a patch against the clean game and a bug report in a player's words.

- **4 reproductions of publicly reported bugs**, from [`bugs/reported/`](../../../bugs/reported/README.md),
  with the reports the known-bugs bench uses. They are marked `tunedOn`: the trace signals were
  built around them, so reproducing them shows less.
- **20 written for this bench** on November 11, 2026, one folder each with `defect.patch` and
  `report.txt`. They were written by the agent that built the bench, from the game's scripts and
  scenes, before any of them was replayed. They are not reports from real players.

By family (issue #282, section 3): movement and input 7, spawning and enemy behaviour 4, collision
and physics 3, state and counters 3, camera and viewport 2, timing and cooldowns 2, HUD and text 1,
layering and draw order 1, visibility and rendering 1. No defect is in "missing or wrong assets".

`authorExpects` says where the author expected each defect to show (the engine's record, the screen,
or both) and was written before any run. It is a label, not a measurement.

```
python3 -m expectrail.repro check          # reads the bench strictly and checks every patch against a copy of the game
```

## What each defect changes in the engine's record

A generated check can only fail on a defect when a probe it uses reads some signal differently on
the defect build than on the clean game. So before asking a model anything, every probe in the
library generated checks draw on ([`expectrail/jit/probes.py`](../../../expectrail/jit/probes.py)) was replayed on the
clean game, twice, and on each defect build, once, and each defect sorted by what changed:

- **signal**: a trace signal reads differently on at least one probe. Any difference counts, so the
  table gives the largest move for a reader to judge.
- **trace-only**: the engine's record differs and no signal does.
- **none**: the record is the same on every probe.

<!-- visibility:start -->
24 defects, 25 probes, Godot 4.7.2-stable, no model. A signal moves: 17. The record differs and no signal does: 2. The record is the same on every probe: 5.

| Defect | Family | Author expected | Measured | Signals that moved: largest move, clean to defect (probes) | Record fields that differ |
| --- | --- | --- | --- | --- | --- |
| `air-jump` | movement-input | both | signal | `air_jumps` 1 to 7 (5), `airborne_ticks` 141 to 181 (4), `max_rise_px` 113.61 to 424.49 (2) | `onFloor`, `player`, `view` |
| `gun-cooldown` | timing-cooldowns | both | signal | `min_projectile_interval_ticks` 48 to 12 (2), `projectile_count` 3 to 12 (2) | `projectiles` |
| `body-flip` | movement-input | both | signal | `enemies_at_end` 3 to 2 (1), `facing_flips` 1 to 240 (8), `facing_mismatch_fraction` 0 to 0.53 (8), `min_enemy_extent_px` 57.74 to 11.92 (3), `player_dx_px` -196.69 to -196.72 (1) | `enemies`, `facing`, `player`, `projectiles`, `view` |
| `enemy-ledge` | spawning-enemies | both | signal | `max_enemy_drop_px` 32.96 to 256.07 (5), `min_enemy_extent_px` 144.46 to 208.9 (25) | `enemies`, `projectiles` |
| `bullet-through-enemy` | collision-physics | both | signal | `enemies_at_end` 2 to 3 (1), `min_enemy_extent_px` 11.92 to 57.74 (3) | `enemies`, `projectiles` |
| `platforms-not-solid` | collision-physics | both | signal | `airborne_ticks` 60 to 86 (2), `max_rise_px` 113.61 to 113 (2) | `onFloor`, `player`, `view` |
| `floaty-fall` | collision-physics | both | signal | `airborne_ticks` 180 to 141 (14), `max_rise_px` 101.5 to 101.49 (1) | `onFloor`, `player`, `view` |
| `jump-always-full` | movement-input | both | signal | `airborne_ticks` 60 to 97 (15), `max_rise_px` 113.61 to 213.04 (13) | `onFloor`, `player`, `view` |
| `slow-left` | movement-input | both | signal | `player_dx_px` 225 to 337.5 (7) | `facing`, `player`, `projectiles`, `view` |
| `slides-after-stop` | movement-input | both | signal | `airborne_ticks` 147 to 173 (6), `max_enemy_drop_px` 0.47 to 0.46 (1), `max_rise_px` 83.49 to 112.93 (7), `player_dx_px` 200.01 to 784.67 (19) | `coins`, `enemies`, `ground`, `onFloor`, `player`, `projectiles`, `view` |
| `no-shooting-in-air` | movement-input | both | none | none | none |
| `jump-needs-rest` | movement-input | both | signal | `air_jumps` 1 to 0 (5), `airborne_ticks` 55 to 1 (10), `max_rise_px` 57.93 to 0 (10), `player_dx_px` -100.01 to -100 (12) | `onFloor`, `player`, `view` |
| `double-jump-once` | state-counters | both | signal | `airborne_ticks` 141 to 178 (5), `max_rise_px` 113.61 to 113.25 (2) | `onFloor`, `player`, `view` |
| `coin-stays` | state-counters | both | signal | `max_enemy_drop_px` 0.47 to 0.46 (1) | `coins`, `enemies` |
| `coin-counts-twice` | state-counters | screen | none | none | none |
| `coin-counter-stuck` | hud-text | screen | none | none | none |
| `gun-cooldown-long` | timing-cooldowns | both | signal | `min_projectile_interval_ticks` 48 to no reading (6), `projectile_count` 5 to 2 (6) | `enemies`, `projectiles` |
| `enemy-missing` | spawning-enemies | both | signal | `enemies_at_end` 3 to 2 (25), `max_enemy_drop_px` 32.96 to 0.07 (5), `min_enemy_extent_px` 44.91 to 44.92 (6), `player_dx_px` -196.69 to -196.72 (1) | `enemies`, `player`, `projectiles`, `view` |
| `enemy-fast-left` | spawning-enemies | both | signal | `min_enemy_extent_px` 144.46 to 210.67 (1) | `enemies` |
| `enemy-slides-when-shot` | spawning-enemies | both | signal | `min_enemy_extent_px` 11.92 to 45.29 (3) | `enemies`, `projectiles` |
| `enemy-walks-backwards` | visibility-rendering | screen | none | none | none |
| `camera-stops-right` | camera-viewport | both | trace-only | none | `view` |
| `camera-cut-top` | camera-viewport | both | trace-only | none | `view` |
| `bullet-behind-scenery` | layering-draw-order | screen | none | none | none |
<!-- visibility:end -->

The record is [`visibility.json`](visibility.json) (`expectrail.repro-visibility/v1`), made by

```
python3 -m expectrail.repro visibility --out runs/repro-visibility --jobs 2     # roughly 20 minutes on two cores
python3 -m expectrail.repro render bench/jit/public/visibility.json
```

in a cloud container on November 11, 2026, with the pinned Godot 4.7.2 and no model. It was not run
in CI. Nothing differed between the two replays of the clean game, and no replay had to be made
again. An earlier full run of the same command, made before four defects were replaced, gave the
same row for each of the 20 defects the two runs share.

What the table shows, and what it does not:

- **It is what the library probes can see, not a rate.** On those 25 probes, with today's signals,
  a generated check could fail on at most 17 of the 24 defects. Whether the model proposes such a
  check, and whether it also passes on the clean game 3 times of 3, is what the live run measures.
  The model may also propose up to four probes of its own for a change; this measurement does not
  replay those, so a live run could reach a defect the library does not.
- **`coin-stays` is in the 17 by a side effect only.** Its one signal moves by a hundredth of a
  pixel (an enemy's drop, 0.47 to 0.46). The symptom itself, coins that stay, is in the record's
  `coins` field, which no signal reads.
- **Both camera defects are trace-only.** The record's `view` field has them and no signal reads it.
- **Five defects leave the record unchanged on every probe**, for three different reasons, which
  this measurement cannot tell apart on its own. Each was looked at by hand in the same session:
  - `no-shooting-in-air`: no probe shoots in the air. On a route that jumps and shoots at once,
    replayed once on each build, the clean game fired 1 bullet and the defect build 0.
  - `enemy-walks-backwards` and `bullet-behind-scenery`: screen only. On a route that walks right
    and fires three times, captured with frames once per build, all 130 frames of the first and
    100 of the second differ from the clean game's (two clean captures were identical); the
    engine's record has no field for either.
  - `coin-counts-twice` and `coin-counter-stuck`: the coin counter is drawn only in the pause menu,
    and no route can open it (the action catalog is move, jump and shoot). **No run has shown these
    two change anything.** They are kept as defects a player would report and no check can reach
    today.

Those hand replays were made once and are not kept as tests.

## What changed while building it

Four defects in the first draft were replaced after replaying them: two camera defects edited
`level/level.gd`, which the level scene does not load, so they changed nothing; an enemy that should
have stuck at a wall never met one within a route's 15 seconds; and an uncapped fall speed needed a
longer drop than any route found. A defect that cannot be shown to change the game does not belong
in a bench, apart from the two counter defects named above.

## How a live run on this bench is made and scored

Built November 11, 2026. **It has not been run**: the workflow mode below has never been
dispatched, and the scorer has only read records from the simulated game and records written by
hand in tests.

**The case.** The generator judges a candidate change, and reproduction has none: the check has to
come from the bug build and the report alone, so that a fix cannot shape the check that later
judges it. So every defect runs with the same stand-in candidate,
[`no-fix.patch`](no-fix.patch): one comment line added to the game's `README.md`, a file the
engine never loads. No profile claim names that file, so the diff map keeps all 25 probes, and
the patch tells the model nothing about any defect. `python3 -m expectrail.repro cases` prints the
24 cases.

What was checked about the no-fix patch, in a cloud container with the pinned Godot 4.7.2, not in
CI: the clean game and each of the 24 defect builds were replayed once on one probe with the patch
and once without, and the engine's record was the same byte for byte in 25 of 25 pairs. That is
one probe and one replay per build, not every probe. A test applies it after every
defect and checks that only the README differs.

**The run.** `jit.yml` has a mode `repro`: from main only, the cases from this folder and nothing
typed at dispatch, each through the same jobs as any live change (measure, propose, replay, one
revision, replay), at the usual $2 cap per defect. The model sees the report, the no-fix patch,
and each probe's signals on the clean game and on the bug build, as it does for any change.

**The score.** `python3 -m expectrail.repro score --records <dir> --out <dir>` reads the 24
records and writes `repro-score.json` (`expectrail.repro-score/v1`) and a page. A defect is
**reproduced** when at least one generated check, in the record's own runs, passed on the clean
game 3 times of 3, failed on the bug build 3 times of 3, and failed 3 times of 3 again on the bug
build with the no-fix patch applied. The last three runs are more than the issue asks: the two
builds behave the same, so a check that fails on one and not the other is flaky and does not
count. The scorer works a check's standing out from its runs and refuses a record whose own flag
disagrees, a record for another candidate, defect or report, and a record that ran each check
some other number of times. A defect with no usable record is **no result**: it stays in the
denominator and is never counted as reproduced.

A miss gets a reason from the issue's vocabulary only where the records can show one:

| Reason | When the scorer gives it |
| --- | --- |
| `budget` | The run ended with `OUT_OF_BUDGET`. |
| `flaky` | A check passed and then did not on the clean game, or failed 3 of 3 on the bug build and then did not with the no-fix patch. |
| `wrong-predicate` | Checks were proposed, none failed 3 of 3 on the bug build, and the table above shows a signal that moves on a library probe. For `coin-stays` that signal is a side effect a hundredth of a pixel wide, so this label would be unfair to the model there. |
| `no-signal` | The table above shows the record differs and no signal does. |
| `undetermined` | The table above shows nothing on any library probe: no route reaches the behaviour, or it shows only on screen. The records cannot say which. |

`route-never-reaches` and `probe-language` are in the vocabulary and the scorer never gives them:
no record separates them from the others. The five defects the table marks `none` were looked at
by hand above; a person carries those findings into the published breakdown.

The score also gives the rate over the defects that change the engine's record on a library probe
(`signal` or `trace-only` in the table, 19 of the 24), which is the set the issue's 70% target is
about, the rate over the 20 defects nothing was tuned on, and spend per defect against the cap.

## What comes next (issue #285)

1. The baseline reproduction rate, from a dispatch of `jit.yml` in mode `repro` on main (a person
   starts it; it costs money).
2. The reason for every miss, from that run's score and, where the records cannot say, by hand.
3. Then reach, signals and proposal quality, in the order the misses decide.
