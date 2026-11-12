# The public reproduction bench

Issue #285 asks for one number: of the reported bugs in a bench, the share for which a generated check
fails on the buggy build 3 times of 3 and passes on the clean game 3 times of 3. This folder is the
bench that number will be measured on. Everything in it is public, and reproduction is developed on
it and on nothing else: never on a blind set, its logs or its counts.

**No reproduction rate has been measured.** That takes a live run from main, which calls a paid
model, and none has been made on this bench. What is here is the bench, two measurements that
need no model (what each defect changes in the engine's record, and what it changes on the screen),
and the scorer that will read a live run's records when there is one.

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

## Reach: routes for what no library probe does

Added November 12, 2026 ([`expectrail/repro/reach.py`](../../../expectrail/repro/reach.py), issue #285 step 3).
The library never presses two different actions close together, except moving while firing. Reach
lists every pair of actions in the game's own catalog that no library route uses together and
makes two short routes for each pair: hold one for half a second and tap the other three times
meanwhile, and the other way round. On this game the pairs are left with right, left with jump,
right with jump, and jump with shoot: eight probes of 160 ticks. No model is asked. The rule was
fixed before any of them was replayed, and is not written for one bug; it was built because
`no-shooting-in-air` showed the gap, so that defect should be read as one this was developed on.

The bug report only orders the probes (the pair it names comes first) and can add nothing. With
eight or fewer to make, every report gets the same eight.

```
python3 -m expectrail.repro reach --report bench/jit/public/no-shooting-in-air/report.txt    # prints the probes; no engine
python3 -m expectrail.repro visibility --reach --out runs/repro-reach --jobs 2               # replays them; no model, no key
python3 -m expectrail.repro render bench/jit/public/visibility-reach.json
```

The same measurement as above, on the eight reach probes in place of the library's 25:

<!-- reach:start -->
24 defects, 8 probes, Godot 4.7.2-stable, no model. A signal moves: 14. The record differs and no signal does: 0. The record is the same on every probe: 10.

| Defect | Family | Author expected | Measured | Signals that moved: largest move, clean to defect (probes) | Record fields that differ |
| --- | --- | --- | --- | --- | --- |
| `air-jump` | movement-input | both | signal | `air_jumps` 2 to 3 (2), `airborne_ticks` 61 to 89 (2), `max_rise_px` 108.17 to 160.58 (1), `player_dx_px` 204.39 to 273.8 (1) | `onFloor`, `player`, `view` |
| `gun-cooldown` | timing-cooldowns | both | signal | `min_projectile_interval_ticks` no reading to 16 (1), `projectile_count` 1 to 3 (1) | `projectiles` |
| `body-flip` | movement-input | both | signal | `facing_flips` 1 to 79 (3), `facing_mismatch_fraction` 0 to 0.67 (3) | `facing`, `player` |
| `enemy-ledge` | spawning-enemies | both | signal | `min_enemy_extent_px` 11.92 to 28.97 (8) | `enemies`, `projectiles` |
| `bullet-through-enemy` | collision-physics | both | signal | `min_enemy_extent_px` 11.92 to 29.15 (1) | `enemies`, `projectiles` |
| `platforms-not-solid` | collision-physics | both | signal | `air_jumps` 1 to 0 (2), `airborne_ticks` 82 to 64 (2), `max_rise_px` 108.17 to 106.8 (1) | `onFloor`, `player`, `view` |
| `floaty-fall` | collision-physics | both | signal | `airborne_ticks` 64 to 83 (6) | `onFloor`, `player`, `view` |
| `jump-always-full` | movement-input | both | signal | `air_jumps` 2 to 1 (1), `airborne_ticks` 61 to 95 (3), `max_rise_px` 108.17 to 199.05 (2) | `onFloor`, `player`, `view` |
| `slow-left` | movement-input | both | signal | `player_dx_px` -196.67 to -88.14 (2) | `player`, `view` |
| `slides-after-stop` | movement-input | both | signal | `air_jumps` 1 to 0 (1), `airborne_ticks` 82 to 50 (1), `player_dx_px` 128 to 301.62 (5) | `onFloor`, `player`, `view` |
| `no-shooting-in-air` | movement-input | both | signal | `projectile_count` 1 to 0 (1) | `projectiles` |
| `jump-needs-rest` | movement-input | both | signal | `air_jumps` 2 to 0 (2), `airborne_ticks` 70 to 1 (2), `max_rise_px` 108.17 to 0 (2), `player_dx_px` 204.39 to 150 (2) | `onFloor`, `player`, `view` |
| `double-jump-once` | state-counters | both | none | none | none |
| `coin-stays` | state-counters | both | none | none | none |
| `coin-counts-twice` | state-counters | screen | none | none | none |
| `coin-counter-stuck` | hud-text | screen | none | none | none |
| `gun-cooldown-long` | timing-cooldowns | both | none | none | none |
| `enemy-missing` | spawning-enemies | both | signal | `enemies_at_end` 3 to 2 (8) | `enemies`, `projectiles` |
| `enemy-fast-left` | spawning-enemies | both | none | none | none |
| `enemy-slides-when-shot` | spawning-enemies | both | signal | `min_enemy_extent_px` 11.92 to 29.15 (1) | `enemies`, `projectiles` |
| `enemy-walks-backwards` | visibility-rendering | screen | none | none | none |
| `camera-stops-right` | camera-viewport | both | none | none | none |
| `camera-cut-top` | camera-viewport | both | none | none | none |
| `bullet-behind-scenery` | layering-draw-order | screen | none | none | none |
<!-- reach:end -->

The record is [`visibility-reach.json`](visibility-reach.json), made in a cloud container on
November 12, 2026, with the pinned Godot 4.7.2 and no model, with four builds replaying at once on
two cores. It was not run in CI. Nothing differed between the two replays of the clean game, and no
replay had to be made again.

What it shows, and what it does not:

- **`no-shooting-in-air` is reached.** On `reach-jump-with-shoot` the clean game fires 1 bullet and
  the defect build 0. With the library's 25 probes and these 8 together, a signal moves on 18 of
  the 24 defects where it was 17.
- **It adds one defect, not more.** The other 13 defects a reach probe shows are ones the library
  already showed. Ten are unchanged on every reach probe: the five the library also leaves
  unchanged less `no-shooting-in-air`, both camera defects, and four the library does show
  (`double-jump-once`, `coin-stays`, `gun-cooldown-long`, `enemy-fast-left`). Reach probes are
  short, and add to the library; they do not replace it.
- **They are not offered to the generator.** Generated checks still draw on the library alone, so
  a live run on this bench, the baseline included, is the same with or without this. Offering them
  is a later change, to be made after the baseline is recorded.
- **It is not a reproduction rate**, for the same reasons as the table above.
- **A reach probe is a route.** This table reads the engine's record along it because that needs
  no model. The same route can be captured with frames for a visual observer; none was here.

## What changed while building it

Four defects in the first draft were replaced after replaying them: two camera defects edited
`level/level.gd`, which the level scene does not load, so they changed nothing; an enemy that should
have stuck at a wall never met one within a route's 15 seconds; and an uncapped fall speed needed a
longer drop than any route found. A defect that cannot be shown to change the game does not belong
in a bench, apart from the two counter defects named above.

## What each defect changes on the screen

Added November 12, 2026 ([`expectrail/repro/screen.py`](../../../expectrail/repro/screen.py)).
Expectrail verifies by observing, so a generated check has to be able to speak about what is drawn
(issue #286), and a defect that shows only on the screen can never be reproduced by a check that
reads the engine's record. Until now "screen only" was a label the bench's author wrote, and two
replays made by hand. This measures it for every defect.

Every library probe was replayed with its frames captured (1600 x 960, 60 a second), on the clean
game twice and on each defect build once. The frames and the engine's record of the same replay
were both compared with the clean game's:

- **record-and-screen**: the record differs on some probe and frames differ on some probe.
- **screen-only**: frames differ; the record is the same on every probe.
- **record-only**: the record differs and every frame is the same.
- **neither**: nothing differs on any probe.

A frame differs when any pixel does. A frame, or a field of the record, that differs between the
two clean replays would be unstable and counted for no defect; none did. How large a difference is
comes from at most eight of a probe's differing frames (the first, the last and evenly between).

<!-- screen:start -->
24 defects, 25 probes, Godot 4.7.2-stable, frames of 1600 x 960, no model. The record and the screen both differ: 19. Only the screen differs: 2. Only the record differs: 0. Nothing differs on any probe: 3.

| Defect | Family | Author expected | Measured | Record fields that differ (probes) | On the screen: the probe where most frames differ | Frames that differ | Most pixels in one frame | Where (left, top, right, bottom) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `air-jump` | movement-input | both | record-and-screen | `onFloor`, `player`, `view` (5) | `jump-w40-x8` (of 5) | 90 of 140, from frame 50 | 12968 (frame 63) | 736, 459, 854, 785 |
| `gun-cooldown` | timing-cooldowns | both | record-and-screen | `projectiles` (2) | `shoot-left-every12` (of 2) | 96 of 123, from frame 27 | 18610 (frame 68) | 373, 667, 840, 806 |
| `body-flip` | movement-input | both | record-and-screen | `enemies`, `facing`, `player`, `projectiles`, `view` (8) | `hold-left` (of 8) | 165 of 170, from frame 5 | 13254 (frame 99) | 621, 0, 1599, 884 |
| `enemy-ledge` | spawning-enemies | both | record-and-screen | `enemies`, `projectiles` (25) | `move-fire-right` (of 3) | 68 of 158, from frame 33 | 22789 (frame 100) | 928, 604, 1473, 806 |
| `bullet-through-enemy` | collision-physics | both | record-and-screen | `enemies`, `projectiles` (3) | `move-fire-right` (of 3) | 125 of 158, from frame 33 | 25100 (frame 68) | 945, 624, 1545, 805 |
| `platforms-not-solid` | collision-physics | both | record-and-screen | `onFloor`, `player`, `view` (2) | `jump-l40-x8` (of 2) | 87 of 140, from frame 47 | 973045 (frame 90) | 0, 0, 1600, 960 |
| `floaty-fall` | collision-physics | both | record-and-screen | `onFloor`, `player`, `view` (14) | `jump-w120-x8` (of 14) | 86 of 180, from frame 92 | 12956 (frame 128) | 736, 501, 854, 785 |
| `jump-always-full` | movement-input | both | record-and-screen | `onFloor`, `player`, `view` (15) | `jump-l40-x8` (of 15) | 107 of 140, from frame 33 | 1009949 (frame 124) | 0, 0, 1600, 960 |
| `slow-left` | movement-input | both | record-and-screen | `facing`, `player`, `projectiles`, `view` (8) | `hold-left` (of 8) | 160 of 170, from frame 10 | 828819 (frame 55) | 0, 0, 1600, 960 |
| `slides-after-stop` | movement-input | both | record-and-screen | `coins`, `enemies`, `ground`, `onFloor`, `player`, `projectiles`, `view` (19) | `jump-w80-x8` (of 19) | 115 of 160, from frame 45 | 1193708 (frame 126) | 0, 0, 1600, 960 |
| `no-shooting-in-air` | movement-input | both | neither | none | none |  |  |  |
| `jump-needs-rest` | movement-input | both | record-and-screen | `onFloor`, `player`, `view` (12) | `jump-l40-x8` (of 12) | 110 of 140, from frame 30 | 997248 (frame 108) | 0, 0, 1600, 960 |
| `double-jump-once` | state-counters | both | record-and-screen | `onFloor`, `player`, `view` (5) | `jump-l40-x8` (of 5) | 69 of 140, from frame 71 | 1004579 (frame 81) | 0, 0, 1600, 960 |
| `coin-stays` | state-counters | both | record-and-screen | `coins`, `enemies` (10) | `jump-w120-x8` (of 12) | 153 of 180, from frame 26 | 7442 (frame 70) | 399, 628, 871, 720 |
| `coin-counts-twice` | state-counters | screen | neither | none | none |  |  |  |
| `coin-counter-stuck` | hud-text | screen | neither | none | none |  |  |  |
| `gun-cooldown-long` | timing-cooldowns | both | record-and-screen | `enemies`, `projectiles` (6) | `move-fire-left` (of 6) | 133 of 158, from frame 25 | 10192 (frame 82) | 686, 666, 840, 806 |
| `enemy-missing` | spawning-enemies | both | record-and-screen | `enemies`, `player`, `projectiles`, `view` (25) | `hold-left` (of 1) | 94 of 170, from frame 76 | 6078 (frame 103) | 673, 8, 1600, 884 |
| `enemy-fast-left` | spawning-enemies | both | record-and-screen | `enemies` (1) | `wait-long` (of 1) | 74 of 575, from frame 501 | 8608 (frame 564) | 1392, 187, 1600, 281 |
| `enemy-slides-when-shot` | spawning-enemies | both | record-and-screen | `enemies`, `projectiles` (3) | `move-fire-right` (of 3) | 68 of 158, from frame 33 | 22789 (frame 100) | 928, 604, 1473, 806 |
| `enemy-walks-backwards` | visibility-rendering | screen | screen-only | none | `jump-w120-x8` (of 25) | 180 of 180, from frame 0 | 16972 (frame 77) | 973, 185, 1600, 792 |
| `camera-stops-right` | camera-viewport | both | record-and-screen | `view` (6) | `jump-w120-x8` (of 6) | 128 of 180, from frame 52 | 899960 (frame 179) | 0, 0, 1600, 960 |
| `camera-cut-top` | camera-viewport | both | record-and-screen | `view` (1) | `jump-l40-x8` (of 1) | 61 of 140, from frame 72 | 980517 (frame 113) | 0, 0, 1600, 960 |
| `bullet-behind-scenery` | layering-draw-order | screen | screen-only | none | `move-fire-left` (of 6) | 153 of 158, from frame 5 | 8079 (frame 27) | 516, 671, 824, 806 |
<!-- screen:end -->

The record is [`screen.json`](screen.json) (`expectrail.repro-screen/v1`), made by

```
python3 -m expectrail.repro screen --out runs/repro-screen --jobs 2     # about two and a half hours on two cores
python3 -m expectrail.repro screen-render bench/jit/public/screen.json
```

in a cloud container on November 12, 2026, with the pinned Godot 4.7.2 drawing in software (Mesa
llvmpipe) and no model: 650 replays. It was not run in CI. No frame and no record field differed
between the two replays of the clean game, on any of the 25 probes, and no replay had to be made
again. The same command again for the two screen-only defects alone gave the same two rows.

What the table shows, and what it does not:

- **Two defects are screen-only, measured: `enemy-walks-backwards` and `bullet-behind-scenery`.**
  The first differs on all 25 probes (from the first frame, on the probe where it shows most); the
  second on the 6 probes that fire.
  Neither changes any field of the engine's record on any probe. These two are the bench's
  screen-only defects for issue #286, and no check in today's closed language can fail on them.
- **No defect is record-only.** Each of the 19 defects whose record differs also changes the
  picture on some probe. So a check about what is drawn could, in principle, fail on 21 of the 24
  on the library's probes; a check on the record's fields, on 19. Neither number is a rate: a
  check still has to be proposed, an observer has to be able to tell the difference, and the check
  has to pass on the clean game 3 times of 3.
- **Per probe the two do not agree, and the record sees more.** `enemy-ledge` and `enemy-missing`
  change the record on all 25 probes and the picture on 3 and on 1: on the others the enemy that
  changed is off the screen. The other way round is rarer: `coin-stays` changes the picture on 12
  probes and the record on 10.
- **Three defects change nothing on any probe, in the record or on the screen.**
  `no-shooting-in-air` needs a route that shoots in the air; the reach probes above have one, and
  they were not captured with frames here. `coin-counts-twice` and `coin-counter-stuck` need the
  pause menu, which no route can open.
- **A whole-frame difference is the camera.** Eight rows have a rectangle of the whole frame and
  about a million pixels: the camera follows the player, so a player a few pixels away from where
  the clean game has it shifts the whole picture. The size of a difference says how much of the
  picture changed, not how plain the defect is to a player.
- **`enemy-ledge` and `enemy-slides-when-shot` have the same row, and it is not a mistake.** On
  `move-fire-right` the two defect builds draw the same 158 frames (checked by replaying that probe
  on both and comparing them with each other), while their records differ in `enemies`.
- **No visual observer was asked anything.** This compares pixels exactly. It says where a watcher
  of the frames could be shown a difference, on which probe and from which frame. Whether SAM or
  any other observer reports that difference is not shown here, and needs recorded or live answers.
- **It is exact for this renderer only.** Another machine's renderer can draw other pixels; the
  record names the one used. Frames are 60 a second and the engine's record has 120 ticks a
  second, so a frame number is not a tick number.
- **It is not a reproduction rate**, and nothing generated checks run on reads it: a live run on
  this bench, the baseline included, is the same with or without it.

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

Where the three sets of runs are read from: the clean game's and the no-fix candidate's are in the
record for every check. The bug build's are kept only for a catch, and a reproducing check is
always a catch, so a check counts only when its catch entry shows three fails on the bug build; a
record that lists the bug build as failed for it and has no such entry gives no result. A `flaky`
miss of the second kind in the table below still rests on the record's list of builds a check
failed on, since the record keeps no runs for it. That can change a reason, never the rate.

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
