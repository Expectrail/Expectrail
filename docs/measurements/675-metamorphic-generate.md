# The generator offers mirror-inputs metamorphic checks: a rehearsal on `slow-left` (#675, piece 3, slice 2)

Measured on November 20, 2026, on the real engine (Godot 4.7.2, headless, locally), by builder two. No model
was called: the proposal is a hand-written stand-in (`model: hand-written-stand-in`) with one trace check, so
the run judges what the generator itself adds. Nothing was dispatched and nothing was spent beyond the local
engine. Public bug only (`bench/jit/public/slow-left/`).

## Setup

- **Bug build:** `bench/jit/public/slow-left/defect.patch` (the player walks left at half speed).
- **Report:** `bench/jit/public/slow-left/report.txt`.
- **Two candidates**, applied on top of the bug build, each in its folder with the proposal and the recorded
  `jit-run.json`:
  - `bench/jit/stand-in/slow-left-metamorphic-comment-only/candidate.patch`: changes one comment in
    `player/player.gd` and leaves the bug;
  - `bench/jit/stand-in/slow-left-metamorphic-revert/candidate.patch`: removes the two lines the defect added.
- **Proposal** (`jit-proposal.json`, the same in both), candidate withheld: one check, "walking right 40 ticks
  before jumping moves the player further right than not walking".

```
EXPECTRAIL_GODOT=tools/godot/Godot_v4.7.2-stable_linux.x86_64 python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/slow-left/report.txt --base bench/jit/public/slow-left/defect.patch \
  --candidate bench/jit/stand-in/slow-left-metamorphic-CANDIDATE/candidate.patch \
  --proposal bench/jit/stand-in/slow-left-metamorphic-CANDIDATE/jit-proposal.json \
  --withhold-candidate --metamorphic --out OUT --run-id mm-slow-left-CANDIDATE
```

Both runs: `status: complete`, 94 replays, $0.1735 and $0.1728 at the assumed runner price (cap $2),
381 s and 376 s wall time with the two runs side by side. Made on main `551cc4c` plus this change, before its
last edit, which touches only what a row says when this stage stops on a replay error or the budget (not met
in these runs). The near-miss generator made no variant of either
candidate, so the bug build is the only near miss.

## Result

- **The stand-in's trace check:** passes the clean game 3 of 3, fails the do-nothing control 3 of 3, and
  passes the bug build: it kills no near miss and is not valid, on both runs.
- **Offered:** 4 pairs, 16 checks (`jump-w40-x2` first, the probe the stand-in uses, then `hold-right`,
  `reverse`, `jump-w40-x1`). Skipped: 6 probes with no mirror, 3 twins of a pair already offered, 12 over the
  limit.
- **Valid: the 4 sideways-travel checks.** Each passes the clean game 3 of 3, is not exercised on the frozen
  player (so the control cannot drop it) and fails the bug build 3 of 3.
- **Comment-only candidate: 4 of 4 catch** (fail 3 of 3). **Revert: 4 of 4 no-catch** (pass 3 of 3).
- The height, airtime and air-jump checks are either not exercised on the clean game (a walk never leaves
  the floor) or pass the bug build, so they are not valid: walking speed does not change them.
- `catches`, `counts` and the gate summary are the same as without `--metamorphic`: nothing here counts.

## Per check

The two runs gave the same clean, control and bug-build outcomes for every check; they differ only on the
candidate.

| Check | Clean (3) | Do-nothing control | Bug build | Valid | Comment-only candidate | Revert candidate |
| --- | --- | --- | --- | --- | --- | --- |
| `mm-mirror-jump-w40-x2-player-dx-px` | pass, pass, pass | indeterminate (not_exercised) | fail, fail, fail | yes | fail, fail, fail: catch | pass, pass, pass: no-catch |
| `mm-mirror-jump-w40-x2-max-rise-px` | pass, pass, pass | indeterminate (not_exercised) | pass | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-jump-w40-x2-airborne-ticks` | pass, pass, pass | indeterminate (not_exercised) | pass | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-jump-w40-x2-air-jumps` | pass, pass, pass | indeterminate (not_exercised) | pass | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-hold-right-player-dx-px` | pass, pass, pass | indeterminate (not_exercised) | fail, fail, fail | yes | fail, fail, fail: catch | pass, pass, pass: no-catch |
| `mm-mirror-hold-right-max-rise-px` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-hold-right-airborne-ticks` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-hold-right-air-jumps` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-reverse-player-dx-px` | pass, pass, pass | indeterminate (not_exercised) | fail, fail, fail | yes | fail, fail, fail: catch | pass, pass, pass: no-catch |
| `mm-mirror-reverse-max-rise-px` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-reverse-airborne-ticks` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-reverse-air-jumps` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-jump-w40-x1-player-dx-px` | pass, pass, pass | indeterminate (not_exercised) | fail, fail, fail | yes | fail, fail, fail: catch | pass, pass, pass: no-catch |
| `mm-mirror-jump-w40-x1-max-rise-px` | pass, pass, pass | indeterminate (not_exercised) | pass | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-jump-w40-x1-airborne-ticks` | pass, pass, pass | indeterminate (not_exercised) | pass | no | -: not-evaluated | -: not-evaluated |
| `mm-mirror-jump-w40-x1-air-jumps` | not_exercised | not-run | - | no | -: not-evaluated | -: not-evaluated |

## What this does not show

- That a model's proposal leaves room for these checks in a live run: none was made.
- Reach beyond defects that depend on the direction the player is sent (slice 1 measured 1 of 24 public
  defects).
- Any outside game (slice 3).
