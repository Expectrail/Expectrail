# Do-nothing control on the public bench's recorded checks (#675, piece 1)

Each trace check in the committed public records was replayed three times on the clean game with the do-nothing control for its class, and judged by the generator's own evaluation. The clean-reference runs are the recorded ones; they were not replayed here. No model was called. Advisory: no record or counting rule changed.

Engine: 4.7.2.stable.official.ed1daf0bf. Records: `bench/jit/recordings/public-43465090517/repro`.

## Controls made from the game

| Class | Mode | File | Patch SHA-256 |
| --- | --- | --- | --- |
| enemy | frozen | enemy/enemy.gd | `beadfacabbd162810a03139a453b308c4e073cbba0bb6e813bbab21bb07da963` |
| player | frozen | player/player.gd | `a34505b86c50a35bf7928f60964827c5951d9fbcd42b414dd726a82f729dca51` |
| projectile | never-made | player/gun.gd | `1905b10e2f57a263bb733edea9abe890735cbffc32c4da0f3fa6535b12cb1ea7` |

## Counts

- Checks in the records: 137. Recorded as passing the clean reference 3 of 3: 135.
- Of those 135: **56 pass the control** (would now be dropped), 35 fail it, 33 are indeterminate (not exercised, mixed, or depending on the frozen player's floor state), 11 not run.
- Kept by the old rule (recorded valid): 91; of these, **41 pass the control** and would now be dropped.

| Class | Passes (dropped) | Fails | Indeterminate | Not run |
| --- | --- | --- | --- | --- |
| player | 29 | 9 | 26 | 3 |
| enemy | 22 | 18 | 0 | 6 |
| projectile | 5 | 8 | 7 | 2 |

- Of the records' 91 recorded catches (all labelled strong), **41 pass the control**. Five public defects
  have every recorded catch pass it: `air-jump`, `enemy-fast-left`, `enemy-ledge`, `slides-after-stop`,
  `slow-left`. Under the new rule a fresh run would keep none of those checks.
- Not run (11): every one uses a model-proposed probe whose route is not in the probe library and is not
  committed beside the record. They were not replayed here.
- Indeterminate (33): checks that need an event to judge (a jump's rise, a shot interval, facing while
  moving), which a frozen actor never gives, and 9 `airborne_ticks` checks whose verdict depends on the
  frozen player's floor state (next section). This control cannot drop them; the near-miss rule still applies.

What passes the control, by predicate: `air_jumps` relations (8 of 8: "eight presses give no more air
jumps than two" holds for a player that never jumps), `player_dx_px` relations (9 of 9), enemy
`max_entity_drop` (6 of 6: a frozen enemy never falls off a ledge), enemy `direction_agreement` (4 of 4),
`entity_present` (1), `facing_flips` (2 of 2), 11 of 24 `min_enemy_extent_px`, 7 of 14 `max_rise_px`,
3 of 17 `airborne_ticks` (upper bounds, which hold for a player that is never airborne), and 5 of 7
`projectile_count` relations (the other 2 not run) ("faster taps give no more shots" holds when no shot
is ever made).

## The frozen player's floor state is not observed

The first measurement (60 pass, 40 fail, 24 indeterminate) judged the frozen player's floor state as the
engine recorded it. On Godot 4.7.2 a frozen player is reported off the floor on every tick: the engine works
out `is_on_floor` in the physics step that the control stops. So its "airborne" time was the length of the
route, and an `airborne_ticks` relation between two routes of different length passed or failed on that
length alone. For example, `double-jump-once` `jit-c2` ("repeated jumps from further right stay airborne
longer") read 240 airborne ticks on `jump-w0-x8` and 360 on `jump-w120-x8` for a player that never left
the ground, and passed.

Now `do_nothing.judge` reads a frozen player's check twice: as recorded, and with the player on the floor on
every tick (no take-off, no landing). The run is `pass` or `fail` only when both readings agree; otherwise it
is `insufficient_observation`, with the reason "cannot tell: the verdict depends on the frozen actor's floor
state". Nine checks moved, all `airborne_ticks`: 4 from passes and 5 from fails to indeterminate. No other
outcome changed. Of the 91 kept by the old rule, 41 now pass the control, not 45.

## Hand check of a sample (requested on #686)

Thirteen checks that passed the control in the first measurement, spread across predicates and classes,
replayed with the control on Godot 4.7.2 and read by hand. Values are each probe's signal on the frozen
build (left, right).

| Public defect | Check | Statement (short) | Frozen values | Reading |
| --- | --- | --- | --- | --- |
| air-jump | `jit-c1` | 8 presses give the same air jumps as 2 | air jumps 0, 0 | trivial: an equality holds when nothing happens |
| air-jump | `jit-c6` | extra presses rise no higher than a double jump | rise 0, 0 px | trivial |
| slow-left | `jit-c4` | walking left while shooting covers the same ground as walking | dx 0, 0 px | trivial |
| slides-after-stop | `jit-c1` | single and double jump after walking cover the same ground | dx 0, 0 px | trivial |
| jump-needs-rest | `jit-c1` | jump after walking rises as high as from standing | rise 0, 0 px | trivial |
| body-flip | `jit-sym-flips-hold` | holding left flips facing no more than holding right | flips 0, 0 | trivial |
| enemy-ledge | `jit-e1` | enemies do not fall far after settling | no drop | trivial: a frozen enemy cannot fall |
| enemy-ledge | `jit-e2` | enemy patrol range bounded | extent 0, 0 px | trivial |
| gun-cooldown | `jit-cooldown-count-right-eq` | tapping faster fires no more bullets | bullets 0, 0 | trivial |
| floaty-fall | `jit-check-w0-single-double` | double jump airborne at most 25 ticks longer than single | 100, 120 recorded; 0, 0 on the floor | trivial upper bound; passes both readings, still dropped |
| double-jump-once | `jit-c2` | further right stays airborne longer (gt 5) | 240, 360 recorded; 0, 0 on the floor | **mishandled**: passed only on the floor-state artifact; now indeterminate |
| double-jump-once | `jit-c3` | far right stays airborne longer than mid right (gt 5) | 320, 360 recorded; 0, 0 on the floor | **mishandled**; now indeterminate |
| platforms-not-solid | `jit-c3-landing-sooner-w80` | landing on the platform is airborne for less time (lt 5) | 200, 160 recorded; 0, 0 on the floor | **mishandled**; now indeterminate |

Ten of the thirteen are trivially passing, as the control claims: equalities and upper bounds between two
routes hold when the actor does nothing. Three passed only because of the floor-state artifact; the hand
check found it, and the fix above covers every check that reads the floor state, not only these three
(`double-jump-once` `jit-c4` moved too). The sample was chosen by hand to cover each predicate, not at random.

## Per check

| Public defect | Check | Class | Predicate | Recorded valid | Control runs | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| air-jump | `jit-c1` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| air-jump | `jit-c2` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| air-jump | `jit-c3` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| air-jump | `jit-c4` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| air-jump | `jit-c5` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| air-jump | `jit-c6` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| gun-cooldown | `jit-cooldown-interval-right` | projectile | min_event_interval | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| gun-cooldown | `jit-cooldown-interval-left` | projectile | min_event_interval | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| gun-cooldown | `jit-cooldown-count-right-eq` | projectile | relation `projectile_count` | yes | pass, pass, pass | passes |
| gun-cooldown | `jit-cooldown-count-left-eq` | projectile | relation `projectile_count` | yes | pass, pass, pass | passes |
| gun-cooldown | `jit-cooldown-gap-right-eq` | projectile | relation `min_projectile_interval_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate |
| gun-cooldown | `jit-cooldown-gap-left-eq` | projectile | relation `min_projectile_interval_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate |
| body-flip | `jit-face-hold-left` | player | direction_agreement | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| body-flip | `jit-face-reverse` | player | direction_agreement | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| body-flip | `jit-face-move-fire-left` | player | direction_agreement | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| body-flip | `jit-face-jump-left` | player | direction_agreement | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| body-flip | `jit-sym-flips-hold` | player | relation `facing_flips` | yes | pass, pass, pass | passes |
| body-flip | `jit-sym-flips-shoot` | player | relation `facing_flips` | yes | pass, pass, pass | passes |
| body-flip | `jit-sym-mismatch-jump` | player | relation `facing_mismatch_fraction` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate |
| enemy-ledge | `jit-e1` | enemy | max_entity_drop | yes | pass, pass, pass | passes |
| enemy-ledge | `jit-e2` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-ledge | `jit-e3` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-ledge | `jit-e4` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-ledge | `jit-e5` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-ledge | `jit-e6` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| bullet-through-enemy | `jit-c1-kill-count` | enemy | relation `enemies_at_end` | yes | fail, fail, fail | fails |
| bullet-through-enemy | `jit-c2-extent-move` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| bullet-through-enemy | `jit-c3-extent-shoot48` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| bullet-through-enemy | `jit-c4-extent-shoot12` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| platforms-not-solid | `jit-c1-landing-sooner-base` | player | relation `airborne_ticks` | yes | fail, fail, fail | fails |
| platforms-not-solid | `jit-c2-landing-sooner-w40` | player | relation `airborne_ticks` | yes | fail, fail, fail | fails |
| platforms-not-solid | `jit-c3-landing-sooner-w80` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| platforms-not-solid | `jit-r-jit-c4-repl-38` | player | relation `airborne_ticks` | yes | - | not-run (route not in the probe library (a model-proposed probe): jit-r-jit-left38-dbl) |
| platforms-not-solid | `jit-r-jit-c5-repl-42` | player | relation `airborne_ticks` | yes | - | not-run (route not in the probe library (a model-proposed probe): jit-r-jit-left42-dbl) |
| floaty-fall | `jit-check-w0-single-double` | player | relation `airborne_ticks` | yes | pass, pass, pass | passes |
| floaty-fall | `jit-check-w40-single-double` | player | relation `airborne_ticks` | yes | pass, pass, pass | passes |
| floaty-fall | `jit-check-w80-single-double` | player | relation `airborne_ticks` | yes | pass, pass, pass | passes |
| floaty-fall | `jit-check-w0-double-multi` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| floaty-fall | `jit-check-w40-double-multi` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| jump-always-full | `jit-tap-low-w0` | player | max_episode_rise | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| jump-always-full | `jit-tap-low-w80` | player | max_episode_rise | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| jump-always-full | `jit-tap-low-l40` | player | max_episode_rise | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| jump-always-full | `jit-double-higher-w40` | player | relation `max_rise_px` | yes | fail, fail, fail | fails |
| jump-always-full | `jit-hold-higher-than-tap` | player | relation `max_rise_px` | yes | - | not-run (route not in the probe library (a model-proposed probe): jit-short-tap, jit-long-hold) |
| jump-always-full | `jit-tap-low-w120` | player | max_episode_rise | yes | not_exercised, not_exercised, not_exercised | indeterminate |
| slow-left | `jit-c4` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slow-left | `jit-c5` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slow-left | `jit-r-jit-d1` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slow-left | `jit-r-jit-d2` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slow-left | `jit-r-jit-d3` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c1` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c2` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c3` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c4` | player | relation `player_dx_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c5` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| slides-after-stop | `jit-c6` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| no-shooting-in-air | `jit-c4` | projectile | relation `projectile_count` | yes | - | not-run (route not in the probe library (a model-proposed probe): jit-ground-shoot-1, jit-air-shoot-1) |
| no-shooting-in-air | `jit-c5` | projectile | relation `projectile_count` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-air-shoot-1, jit-air-shoot-2) |
| jump-needs-rest | `jit-c1` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| jump-needs-rest | `jit-c2` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| jump-needs-rest | `jit-c3` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| jump-needs-rest | `jit-c4` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| jump-needs-rest | `jit-c5` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| jump-needs-rest | `jit-c6` | player | relation `air_jumps` | yes | pass, pass, pass | passes |
| jump-needs-rest | `jit-c7` | player | relation `max_rise_px` | yes | pass, pass, pass | passes |
| jump-needs-rest | `jit-c8` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| double-jump-once | `jit-c1` | player | relation `airborne_ticks` | yes | fail, fail, fail | fails |
| double-jump-once | `jit-c2` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| double-jump-once | `jit-c3` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| double-jump-once | `jit-c4` | player | relation `airborne_ticks` | yes | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate (cannot tell: the verdict depends on the frozen actor's floor state, which the engine does not work out while its physics step is stopped) |
| coin-stays | `jit-r-jump-double-higher-w40` | player | relation `max_rise_px` | no | fail, fail, fail | fails |
| coin-stays | `jit-r-jump-eight-capped-w40` | player | max_episode_rise | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-stays | `jit-r-cooldown-limits-left` | projectile | min_event_interval | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-stays | `jit-r-rapid-press-same-left` | projectile | relation `projectile_count` | no | pass, pass, pass | passes |
| coin-stays | `jit-r-facing-follows-hold-right` | player | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-stays | `jit-r-enemies-dont-fall-hold-right` | enemy | max_entity_drop | no | pass, pass, pass | passes |
| coin-stays | `jit-r-enemies-patrol-wait-long` | enemy | min_motion_extent | no | fail, fail, fail | fails |
| coin-counts-twice | `jit-r-reg-double-higher-w40` | player | relation `max_rise_px` | no | fail, fail, fail | fails |
| coin-counts-twice | `jit-r-reg-no-triple-rise-w80` | player | max_episode_rise | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-counts-twice | `jit-r-reg-cooldown-left` | projectile | min_event_interval | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-counts-twice | `jit-r-reg-facing-hold-right` | player | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-counts-twice | `jit-r-reg-enemy-no-fall-left` | enemy | max_entity_drop | no | pass, pass, pass | passes |
| coin-counts-twice | `jit-r-reg-enemy-present-hold` | enemy | entity_present | no | pass, pass, pass | passes |
| coin-counter-stuck | `jit-r-jit-double-rise-b` | player | relation `max_rise_px` | no | fail, fail, fail | fails |
| coin-counter-stuck | `jit-r-jit-jump-limit-b` | player | relation `air_jumps` | no | pass, pass, pass | passes |
| coin-counter-stuck | `jit-r-jit-cooldown-left` | projectile | relation `projectile_count` | no | pass, pass, pass | passes |
| coin-counter-stuck | `jit-r-jit-facing-left` | player | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| coin-counter-stuck | `jit-r-jit-patrol-drop-b` | enemy | max_entity_drop | no | pass, pass, pass | passes |
| coin-counter-stuck | `jit-r-jit-patrol-motion-b` | enemy | min_motion_extent | no | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c1` | projectile | min_event_count | yes | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c2` | projectile | min_event_count | yes | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c3` | projectile | min_event_count | yes | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c4` | projectile | min_event_count | yes | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c5` | projectile | min_event_count | yes | fail, fail, fail | fails |
| gun-cooldown-long | `jit-c6` | projectile | min_event_count | yes | fail, fail, fail | fails |
| enemy-missing | `jit-c3` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-missing | `jit-c4` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-missing | `jit-c5` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-missing | `jit-c6` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-missing | `jit-r-jit-c7` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-missing | `jit-r-jit-c8` | enemy | relation `max_enemy_drop_px` | yes | fail, fail, fail | fails |
| enemy-fast-left | `jit-enemy-extent-long-vs-short-right` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-fast-left | `jit-enemy-extent-long-vs-short-left` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-fast-left | `jit-enemy-extent-long-vs-reverse` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-shoot-right` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-jump-short` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-movefire-right` | enemy | relation `min_enemy_extent_px` | yes | pass, pass, pass | passes |
| enemy-slides-when-shot | `jit-c1` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| enemy-slides-when-shot | `jit-c2` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| enemy-slides-when-shot | `jit-c3` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| enemy-slides-when-shot | `jit-c4` | enemy | relation `min_enemy_extent_px` | yes | fail, fail, fail | fails |
| enemy-walks-backwards | `jit-enemy-faces-travel-wait` | enemy | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| enemy-walks-backwards | `jit-enemy-faces-travel-right` | enemy | direction_agreement | no | pass, pass, pass | passes |
| enemy-walks-backwards | `jit-enemy-faces-travel-left` | enemy | direction_agreement | no | pass, pass, pass | passes |
| enemy-walks-backwards | `jit-enemy-faces-travel-reverse` | enemy | direction_agreement | no | pass, pass, pass | passes |
| enemy-walks-backwards | `jit-enemy-faces-travel-shootr` | enemy | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| enemy-walks-backwards | `jit-enemy-faces-travel-shootl` | enemy | direction_agreement | no | pass, pass, pass | passes |
| camera-stops-right | `jit-r-far-e1` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-8s) |
| camera-stops-right | `jit-r-far-e2` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-12s) |
| camera-stops-right | `jit-r-far-e3` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-12s) |
| camera-stops-right | `jit-r-far-e6` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-single) |
| camera-stops-right | `jit-r-far-e7` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-double) |
| camera-stops-right | `jit-r-far-e8` | enemy | relation `min_enemy_extent_px` | no | - | not-run (route not in the probe library (a model-proposed probe): jit-r-far-right-double) |
| camera-cut-top | `jit-c1-double-higher` | player | relation `max_rise_px` | no | fail, fail, fail | fails |
| camera-cut-top | `jit-c2-only-one-air-jump` | player | relation `air_jumps` | no | pass, pass, pass | passes |
| camera-cut-top | `jit-c3-cooldown-limits` | projectile | relation `projectile_count` | no | pass, pass, pass | passes |
| camera-cut-top | `jit-c4-facing` | player | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| camera-cut-top | `jit-c5-no-fall` | enemy | max_entity_drop | no | pass, pass, pass | passes |
| camera-cut-top | `jit-c6-patrol-moves` | enemy | min_motion_extent | no | fail, fail, fail | fails |
| bullet-behind-scenery | `jit-r-jit-d1` | projectile | min_event_count | no | fail, fail, fail | fails |
| bullet-behind-scenery | `jit-r-jit-d2` | projectile | min_event_interval | no | not_exercised, not_exercised, not_exercised | indeterminate |
| bullet-behind-scenery | `jit-r-jit-d3` | player | direction_agreement | no | not_exercised, not_exercised, not_exercised | indeterminate |
| bullet-behind-scenery | `jit-r-jit-d4` | enemy | max_entity_drop | no | pass, pass, pass | passes |
| bullet-behind-scenery | `jit-r-jit-d5` | enemy | relation `enemies_at_end` | no | fail, fail, fail | fails |
| bullet-behind-scenery | `jit-r-jit-d6` | player | relation `max_rise_px` | no | fail, fail, fail | fails |
| bullet-behind-scenery | `jit-r-jit-d7` | projectile | event_response | no | fail, fail, fail | fails |
| bullet-behind-scenery | `jit-r-jit-d8` | player | max_episode_rise | no | not_exercised, not_exercised, not_exercised | indeterminate |
