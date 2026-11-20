# Mirror-inputs metamorphic checks on the bundled game and the public bugs (#675, piece 3)

Each library probe that uses a left/right action was paired with its mirror (left and right swapped), and one check per signal was made from the pair (`expectrail/jit/metamorphic.py`). Each route was replayed three times on the clean game, three times on the player's do-nothing control, and once on each public bench defect, and judged by the generator's own evaluation. No model was called. Advisory: the generator does not offer these checks yet, and no record or counting rule changed.

Engine: 4.7.2.stable.official.ed1daf0bf. Produced by `python3 tools/metamorphic_public.py`.

## Counts

- Pairs: 14 (twin pairs that are the same two routes measured once). Checks: 56.
- Clean game, outcomes over the three runs: 28 not_exercised, 28 pass. **28 pass 3 of 3** and are usable.
- Of those, on the do-nothing control: 28 indeterminate. **28 are kept** (usable, and not passing the control).
- Public defects with at least one kept check failing on them: **1 of 24**: `slow-left`.

## Per check

| Check | Pair | Clean (3) | Do-nothing (3) | Kept | Fails on (one run each) |
| --- | --- | --- | --- | --- | --- |
| `mm-mirror-hold-right-player-dx-px` | hold-right / hold-right-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-hold-right-max-rise-px` | hold-right / hold-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-hold-right-airborne-ticks` | hold-right / hold-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-hold-right-air-jumps` | hold-right / hold-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-reverse-player-dx-px` | reverse / reverse-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-reverse-max-rise-px` | reverse / reverse-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-reverse-airborne-ticks` | reverse / reverse-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-reverse-air-jumps` | reverse / reverse-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w40-x1-player-dx-px` | jump-w40-x1 / jump-w40-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w40-x1-max-rise-px` | jump-w40-x1 / jump-w40-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x1-airborne-ticks` | jump-w40-x1 / jump-w40-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x1-air-jumps` | jump-w40-x1 / jump-w40-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w40-x2-player-dx-px` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w40-x2-max-rise-px` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x2-airborne-ticks` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x2-air-jumps` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x8-player-dx-px` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w40-x8-max-rise-px` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x8-airborne-ticks` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w40-x8-air-jumps` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x1-player-dx-px` | jump-w80-x1 / jump-w80-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w80-x1-max-rise-px` | jump-w80-x1 / jump-w80-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x1-airborne-ticks` | jump-w80-x1 / jump-w80-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x1-air-jumps` | jump-w80-x1 / jump-w80-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w80-x2-player-dx-px` | jump-w80-x2 / jump-w80-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w80-x2-max-rise-px` | jump-w80-x2 / jump-w80-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x2-airborne-ticks` | jump-w80-x2 / jump-w80-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x2-air-jumps` | jump-w80-x2 / jump-w80-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w80-x8-player-dx-px` | jump-w80-x8 / jump-w80-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w80-x8-max-rise-px` | jump-w80-x8 / jump-w80-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x8-airborne-ticks` | jump-w80-x8 / jump-w80-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | - |
| `mm-mirror-jump-w80-x8-air-jumps` | jump-w80-x8 / jump-w80-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x1-player-dx-px` | jump-w120-x1 / jump-w120-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w120-x1-max-rise-px` | jump-w120-x1 / jump-w120-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x1-airborne-ticks` | jump-w120-x1 / jump-w120-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x1-air-jumps` | jump-w120-x1 / jump-w120-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x2-player-dx-px` | jump-w120-x2 / jump-w120-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w120-x2-max-rise-px` | jump-w120-x2 / jump-w120-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x2-airborne-ticks` | jump-w120-x2 / jump-w120-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x2-air-jumps` | jump-w120-x2 / jump-w120-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x8-player-dx-px` | jump-w120-x8 / jump-w120-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-jump-w120-x8-max-rise-px` | jump-w120-x8 / jump-w120-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x8-airborne-ticks` | jump-w120-x8 / jump-w120-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-jump-w120-x8-air-jumps` | jump-w120-x8 / jump-w120-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every48-player-dx-px` | shoot-left-every48 / shoot-left-every48-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-shoot-left-every48-max-rise-px` | shoot-left-every48 / shoot-left-every48-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every48-airborne-ticks` | shoot-left-every48 / shoot-left-every48-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every48-air-jumps` | shoot-left-every48 / shoot-left-every48-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every12-player-dx-px` | shoot-left-every12 / shoot-left-every12-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-shoot-left-every12-max-rise-px` | shoot-left-every12 / shoot-left-every12-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every12-airborne-ticks` | shoot-left-every12 / shoot-left-every12-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-shoot-left-every12-air-jumps` | shoot-left-every12 / shoot-left-every12-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-move-fire-right-player-dx-px` | move-fire-right / move-fire-right-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | slow-left |
| `mm-mirror-move-fire-right-max-rise-px` | move-fire-right / move-fire-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-move-fire-right-airborne-ticks` | move-fire-right / move-fire-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |
| `mm-mirror-move-fire-right-air-jumps` | move-fire-right / move-fire-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | - |

## Per defect

| Public defect | Family | Kept checks failing | Outcomes of kept checks |
| --- | --- | --- | --- |
| air-jump | movement-input | 0 | 28 pass |
| gun-cooldown | timing-cooldowns | 0 | 28 pass |
| body-flip | movement-input | 0 | 28 pass |
| enemy-ledge | spawning-enemies | 0 | 28 pass |
| bullet-through-enemy | collision-physics | 0 | 28 pass |
| platforms-not-solid | collision-physics | 0 | 28 pass |
| floaty-fall | collision-physics | 0 | 28 pass |
| jump-always-full | movement-input | 0 | 28 pass |
| slow-left | movement-input | 14 | 14 fail, 14 pass |
| slides-after-stop | movement-input | 0 | 8 not_exercised, 20 pass |
| no-shooting-in-air | movement-input | 0 | 28 pass |
| jump-needs-rest | movement-input | 0 | 9 not_exercised, 19 pass |
| double-jump-once | state-counters | 0 | 28 pass |
| coin-stays | state-counters | 0 | 28 pass |
| coin-counts-twice | state-counters | 0 | 28 pass |
| coin-counter-stuck | hud-text | 0 | 28 pass |
| gun-cooldown-long | timing-cooldowns | 0 | 28 pass |
| enemy-missing | spawning-enemies | 0 | 28 pass |
| enemy-fast-left | spawning-enemies | 0 | 28 pass |
| enemy-slides-when-shot | spawning-enemies | 0 | 28 pass |
| enemy-walks-backwards | visibility-rendering | 0 | 28 pass |
| camera-stops-right | camera-viewport | 0 | 28 pass |
| camera-cut-top | camera-viewport | 0 | 28 pass |
| bullet-behind-scenery | layering-draw-order | 0 | 28 pass |

## Probes with no mirror

- `wait-long`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `hold-left`: the same two programs as a pair already measured
- `jump-w0-x1`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `jump-w0-x2`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `jump-w0-x8`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `shoot-right-every48`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `shoot-right-every12`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `move-fire-left`: the same two programs as a pair already measured
- `jump-l40-x1`: the same two programs as a pair already measured
- `jump-l40-x2`: the same two programs as a pair already measured
- `jump-l40-x8`: the same two programs as a pair already measured

## What this shows, and what it does not

- **Every usable check states an obligation the do-nothing control cannot meet.** All 28 are not exercised
  on a frozen player (it never moves 8 px sideways), so none would be dropped by piece 1's rule, and none
  passes by default. Piece 1 found 56 of 135 recorded checks passing that control.
- **No false catch.** On the 23 public defects other than `slow-left`, every kept check passes or is not
  exercised (one run each).
- **Reach is narrow, as expected.** Mirroring the player's inputs can only catch a defect whose effect
  depends on the direction the player is sent. Of the 24 public defects only `slow-left` does, and 14
  kept checks catch it. A defect that is the same on both sides (`air-jump`, `jump-always-full`), an
  enemy's own direction (`enemy-fast-left`, `enemy-walks-backwards`), or facing (`body-flip`, not a
  compared signal: the player starts facing right, so mirroring adds a turn) is out of its reach.
- **The level limits the window.** A wall about 196 px left of the start ends most clear windows near
  tick 97 to 102, and a ceiling to the right ends the jump windows at tick 93. 28 of the 56 checks are
  not exercised on the clean game for that reason or because nothing jumped in the window.

## Calibration of the clear window, and one change made after seeing results

The bounds in `MIRROR` (`expectrail/trace/evaluator.py`) were read from clean-game traces (Godot 4.7.2):
gravity adds 0.146 px a tick to the fall; a walk speeds up and slows down by 0.125 px a tick to 2.5 px a
tick; standing still moves the player under 0.1 px a tick; a ceiling hit changes the fall by +1.44 px in
one tick; a wall stops a full-speed walk by 2.5 px in one tick.

The first full run used a sideways bound of 1.0 px and let any input change within two ticks explain a
sideways change. Three checks then failed 3 of 3 on the clean game (`jump-w80-x1`, `-x2`, `-x8`,
`player_dx_px`): the player, slowing after its walk, met the left wall at tick 102, two ticks after a
jump press, with a change of 0.85 px. The bound is now 0.5 px, and only a left/right input explains a
sideways change (a jump press does not change sideways speed on this game). The same saved replays were
judged again (`--resume`, no replay re-run). What changed, all from the wall at tick 102 now being seen:

- the three `jump-w80` `player_dx_px` checks: clean fail 3 of 3 to pass 3 of 3; on 22 defects fail to
  pass (those failures were the same false failure); on `slow-left` still fail;
- `jump-w80-x2` and `jump-w80-x8` `air_jumps`: clean pass 3 of 3 to not exercised (the window now ends
  at the wall, before the second jump press), so they are no longer usable; on 21 and 22 defects, pass
  to not exercised likewise;
- six other single defect runs (`max_rise_px`, `airborne_ticks` and `air_jumps` checks): pass to not
  exercised.

No defect run went from pass to fail. Before: 27 usable, 11 kept checks catching `slow-left`. After: 28
usable, 14. This was tuned on the clean game's traces with the public defects' results in view; no
held-out material was used.
