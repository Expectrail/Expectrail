# Mirror-inputs metamorphic checks on kinematic-character (#675, piece 3, slice 3)

Source: the `metamorphic-outside` job of [run 44788077524](https://github.com/Expectrail/Expectrail/actions/runs/44788077524/job/136468151181) (pull request #719, head `b22aaa8`, conclusion success, 17:56 to 18:00 UTC). The text below is the job's own output, copied from its log.

Project: `https://github.com/godotengine/godot-demo-projects.git`, `2d/kinematic_character`, commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`, MIT. Actions from its `project.godot`: `jump`, `move_left`, `move_right`. Sandbox: `require`. Engine: 4.7.2.stable.official.ed1daf0bf. No model was called. Advisory: no record or counting rule changed.

## Counts

- Pairs: 11. Checks: 44. Replays completed: 220; routes with a failed replay or differing runs: 0.
- As pinned, outcomes over the three runs: 22 not_exercised, 22 pass. **22 pass 3 of 3** and are usable.
- Of those, on the do-nothing control: 22 indeterminate. **22 are kept.**
- `broken` (defect: the player's collision mask is emptied, so it falls through the floor): **0 kept checks catch it**.
- `harmless` (harmless: the player's sprite is tinted; nothing it does changes (the engine's checks pass, as on the project unchanged; CI has no vision key, so the verdict is needs-review, as #379 requires: an accept needs vision, and an outside project counts as verified only after a run with vision, Sean's call on #398)): **0 kept checks fail it (false rejects)**.
- `invisible` (harmless: the player's sprite is hidden; it moves exactly as before, so the engine's checks pass and only a visual observer can tell (#330): with vision it must not be accepted, because no player is drawn where the engine says it is): **0 kept checks fail it (false rejects)**.
- `drag-left` (defect: seeded here: while move_left is held, the player is pushed 1 px back to the right each tick): **11 kept checks catch it**: `mm-mirror-hold-right-player-dx-px`, `mm-mirror-jump-w120-x1-player-dx-px`, `mm-mirror-jump-w120-x2-player-dx-px`, `mm-mirror-jump-w120-x8-player-dx-px`, `mm-mirror-jump-w40-x1-player-dx-px`, `mm-mirror-jump-w40-x2-player-dx-px`, `mm-mirror-jump-w40-x8-player-dx-px`, `mm-mirror-jump-w80-x1-player-dx-px`, `mm-mirror-jump-w80-x2-player-dx-px`, `mm-mirror-jump-w80-x8-player-dx-px`, `mm-mirror-reverse-player-dx-px`.

## Per check

| Check | Pair | As pinned (3) | Do-nothing (3) | Kept | broken (1) | harmless (1) | invisible (1) | drag-left (1) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mm-mirror-hold-right-player-dx-px` | hold-right / hold-right-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-hold-right-max-rise-px` | hold-right / hold-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-hold-right-airborne-ticks` | hold-right / hold-right-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-hold-right-air-jumps` | hold-right / hold-right-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-reverse-player-dx-px` | reverse / reverse-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-reverse-max-rise-px` | reverse / reverse-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-reverse-airborne-ticks` | reverse / reverse-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-reverse-air-jumps` | reverse / reverse-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x1-player-dx-px` | jump-w40-x1 / jump-w40-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w40-x1-max-rise-px` | jump-w40-x1 / jump-w40-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x1-airborne-ticks` | jump-w40-x1 / jump-w40-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w40-x1-air-jumps` | jump-w40-x1 / jump-w40-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x2-player-dx-px` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w40-x2-max-rise-px` | jump-w40-x2 / jump-w40-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x2-airborne-ticks` | jump-w40-x2 / jump-w40-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w40-x2-air-jumps` | jump-w40-x2 / jump-w40-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x8-player-dx-px` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w40-x8-max-rise-px` | jump-w40-x8 / jump-w40-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w40-x8-airborne-ticks` | jump-w40-x8 / jump-w40-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w40-x8-air-jumps` | jump-w40-x8 / jump-w40-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x1-player-dx-px` | jump-w80-x1 / jump-w80-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w80-x1-max-rise-px` | jump-w80-x1 / jump-w80-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x1-airborne-ticks` | jump-w80-x1 / jump-w80-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w80-x1-air-jumps` | jump-w80-x1 / jump-w80-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x2-player-dx-px` | jump-w80-x2 / jump-w80-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w80-x2-max-rise-px` | jump-w80-x2 / jump-w80-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x2-airborne-ticks` | jump-w80-x2 / jump-w80-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w80-x2-air-jumps` | jump-w80-x2 / jump-w80-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x8-player-dx-px` | jump-w80-x8 / jump-w80-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w80-x8-max-rise-px` | jump-w80-x8 / jump-w80-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w80-x8-airborne-ticks` | jump-w80-x8 / jump-w80-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w80-x8-air-jumps` | jump-w80-x8 / jump-w80-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x1-player-dx-px` | jump-w120-x1 / jump-w120-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w120-x1-max-rise-px` | jump-w120-x1 / jump-w120-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x1-airborne-ticks` | jump-w120-x1 / jump-w120-x1-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w120-x1-air-jumps` | jump-w120-x1 / jump-w120-x1-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x2-player-dx-px` | jump-w120-x2 / jump-w120-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w120-x2-max-rise-px` | jump-w120-x2 / jump-w120-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x2-airborne-ticks` | jump-w120-x2 / jump-w120-x2-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w120-x2-air-jumps` | jump-w120-x2 / jump-w120-x2-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x8-player-dx-px` | jump-w120-x8 / jump-w120-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | fail |
| `mm-mirror-jump-w120-x8-max-rise-px` | jump-w120-x8 / jump-w120-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |
| `mm-mirror-jump-w120-x8-airborne-ticks` | jump-w120-x8 / jump-w120-x8-mirror | pass, pass, pass | not_exercised, not_exercised, not_exercised | yes | pass | pass | pass | pass |
| `mm-mirror-jump-w120-x8-air-jumps` | jump-w120-x8 / jump-w120-x8-mirror | not_exercised, not_exercised, not_exercised | not_exercised, not_exercised, not_exercised | no | not_exercised | not_exercised | not_exercised | not_exercised |

## Probes with no mirror

- `wait-long`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `hold-left`: the same two programs as a pair already measured
- `jump-w0-x1`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `jump-w0-x2`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `jump-w0-x8`: cannot tell: the probe uses no paired action, so the mirror changes nothing
- `jump-l40-x1`: the same two programs as a pair already measured
- `jump-l40-x2`: the same two programs as a pair already measured
- `jump-l40-x8`: the same two programs as a pair already measured
